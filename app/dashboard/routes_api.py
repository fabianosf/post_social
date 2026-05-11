"""
Endpoints JSON do dashboard: status, agenda semanal, IA, métricas, insights.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import jsonify, request, url_for, current_app
from flask_login import login_required, current_user

from ..models import db, InstagramAccount, PostQueue
from .helpers import SAFE_LIMITS, BRAZIL_TZ
from . import dashboard_bp


@dashboard_bp.route("/api/dashboard/stats")
@login_required
def api_dashboard_stats():
    from sqlalchemy import func as _f
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = (db.session.query(PostQueue.status, _f.count().label("n"))
            .filter(PostQueue.client_id == current_user.id)
            .group_by(PostQueue.status).all())
    sc = {r.status: r.n for r in rows}
    scheduled = (PostQueue.query
                 .filter(PostQueue.client_id == current_user.id,
                         PostQueue.status == "pending",
                         PostQueue.scheduled_at.isnot(None),
                         PostQueue.scheduled_at > now_utc)
                 .count())
    return jsonify({
        "total":      sum(sc.values()),
        "posted":     sc.get("posted", 0),
        "queued":     sc.get("pending", 0) - scheduled,
        "scheduled":  scheduled,
        "failed":     sc.get("failed", 0),
        "processing": sc.get("processing", 0),
    })


@dashboard_bp.route("/api/status")
@login_required
def api_status():
    notifications = PostQueue.query.filter_by(
        client_id=current_user.id, notified=False
    ).filter(PostQueue.status.in_(["posted", "failed"])).count()
    return jsonify({"pending_notifications": notifications})


@dashboard_bp.route("/api/week-schedule")
@login_required
def api_week_schedule():
    today = datetime.now(BRAZIL_TZ).date()

    account_id = request.args.get("account_id", type=int)
    all_accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()
    if account_id:
        target_accs = [a for a in all_accounts if a.id == account_id]
    else:
        target_accs = all_accounts[:1]

    if not target_accs:
        return jsonify([])

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    day_names = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    MAX_DAY = SAFE_LIMITS["max_posts_per_day"]
    week = []

    for i in range(7):
        day = today + timedelta(days=i)
        day_start_brt = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=BRAZIL_TZ)
        day_end_brt   = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=BRAZIL_TZ)
        day_start = day_start_brt.astimezone(timezone.utc).replace(tzinfo=None)
        day_end   = day_end_brt.astimezone(timezone.utc).replace(tzinfo=None)

        posts_out = []
        ig_count = 0
        fb_count = 0

        for acc in target_accs:
            posts = (
                PostQueue.query.filter(
                    PostQueue.account_id == acc.id,
                    PostQueue.post_type != "story",
                    PostQueue.status.in_(["pending", "posted", "processing"]),
                    db.or_(
                        db.and_(PostQueue.scheduled_at >= day_start, PostQueue.scheduled_at <= day_end),
                        db.and_(PostQueue.posted_at >= day_start, PostQueue.posted_at <= day_end),
                    ),
                )
                .order_by(PostQueue.scheduled_at)
                .all()
            )

            for p in posts:
                if p.post_to_instagram:
                    ig_count += 1
                if p.post_to_facebook:
                    fb_count += 1

                thumb_url = ""
                first_path = p.image_path.split("|")[0]
                if first_path.startswith(upload_folder):
                    rel = first_path[len(upload_folder):].lstrip("/")
                    thumb_url = url_for("dashboard.uploaded_file", filename=rel)

                sched_time = ""
                if p.scheduled_at:
                    local_t = p.scheduled_at.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)
                    sched_time = local_t.strftime("%H:%M")
                elif p.posted_at:
                    local_t = p.posted_at.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)
                    sched_time = local_t.strftime("%H:%M")

                posts_out.append({
                    "id": p.id,
                    "filename": p.image_filename[:25],
                    "time": sched_time,
                    "status": p.status,
                    "ig": bool(p.post_to_instagram),
                    "fb": bool(p.post_to_facebook),
                    "thumb_url": thumb_url,
                    "is_video": p.post_type == "reels",
                })

        week.append({
            "date": day.isoformat(),
            "weekday": day.weekday(),
            "day_name": day_names[day.weekday()],
            "day_short": day.strftime("%d/%m"),
            "posts": posts_out,
            "ig_count": ig_count,
            "fb_count": fb_count,
            "max": MAX_DAY,
            "is_today": day == today,
            "is_past": day < today,
        })

    return jsonify(week)


@dashboard_bp.route("/api/ai-caption", methods=["POST"])
@login_required
def api_generate_caption():
    from modules.caption_generator import CaptionGenerator
    from modules.logger import setup_global_logger

    filename = request.json.get("filename", "foto.jpg")
    multiple = request.json.get("multiple", True)
    logger = setup_global_logger(".")
    gen = CaptionGenerator(logger, provider="groq")

    if multiple:
        captions = gen.generate_multiple(image_name=filename, count=3, tone="profissional e amigável", language="pt-br")
        return jsonify({"captions": captions, "caption": captions[0] if captions else ""})
    else:
        caption = gen.generate(image_name=filename, tone="profissional e amigável", language="pt-br")
        return jsonify({"caption": caption, "captions": [caption]})


@dashboard_bp.route("/api/post-metrics/<int:post_id>")
@login_required
def api_post_metrics(post_id):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if not post or not post.instagram_media_id:
        return jsonify({"error": "Post sem métricas disponíveis"}), 404

    account = InstagramAccount.query.filter_by(
        id=post.account_id, client_id=current_user.id
    ).first()
    if not account:
        return jsonify({"error": "Conta não encontrada"}), 404

    from modules.metrics import fetch_post_metrics
    session_dir = str(Path(current_app.root_path).parent / "sessions")
    metrics = fetch_post_metrics(account, post.instagram_media_id, session_dir)

    if metrics:
        return jsonify(metrics)
    return jsonify({"error": "Não foi possível buscar métricas"}), 500


@dashboard_bp.route("/api/best-time", methods=["POST"])
@login_required
def api_best_time():
    from modules.caption_generator import CaptionGenerator
    from modules.logger import setup_global_logger

    logger = setup_global_logger(".")
    gen = CaptionGenerator(logger, provider="groq")

    if not gen.client:
        return jsonify({"suggestion": "Melhores horários gerais: 8h-9h, 12h-13h, 18h-20h"})

    posted = PostQueue.query.filter_by(
        client_id=current_user.id, status="posted"
    ).order_by(PostQueue.posted_at.desc()).limit(30).all()

    history = ""
    if posted:
        hours = [p.posted_at.strftime("%H:%M") for p in posted if p.posted_at]
        days = [p.posted_at.strftime("%A") for p in posted if p.posted_at]
        history = f"Histórico de postagens (horários): {', '.join(hours[:20])}. Dias: {', '.join(days[:20])}."

    prompt = (
        f"Baseado no seguinte histórico de posts no Instagram, sugira os 3 melhores horários "
        f"e dias da semana para postar para máximo engajamento. "
        f"{history} "
        f"Responda em português de forma curta e direta (máx 3 linhas). "
        f"Se não houver histórico, sugira horários gerais baseados em pesquisas de mercado."
    )

    try:
        generators = {
            "groq": gen._generate_groq,
            "openai": gen._generate_openai,
            "anthropic": gen._generate_anthropic,
            "gemini": gen._generate_gemini,
            "ollama": gen._generate_ollama,
        }
        gen_fn = generators.get(gen.provider)
        suggestion = gen_fn(prompt) if gen_fn else "Melhores horários: 8h-9h, 12h-13h, 18h-20h"
        return jsonify({"suggestion": suggestion})
    except Exception:
        return jsonify({"suggestion": "Melhores horários gerais: 8h-9h, 12h-13h, 18h-20h"})


@dashboard_bp.route("/api/refresh-insights", methods=["POST"])
@login_required
def refresh_insights():
    import os as _os
    # __file__ is app/dashboard/routes_api.py → go up 3 levels to project root
    SESSION_DIR = Path(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__)))) / "sessions"
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id, status="active").all()
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    updated = 0
    errors = []

    for account in accounts:
        session_file = SESSION_DIR / f"account_{account.id}.json"
        if not session_file.exists():
            continue
        try:
            from instagrapi import Client as IGClient
            cl = IGClient()
            cl.delay_range = [1, 3]
            cl.load_settings(session_file)
            cl.get_timeline_feed()

            posts = PostQueue.query.filter(
                PostQueue.account_id == account.id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= week_ago,
                PostQueue.instagram_media_id.isnot(None),
            ).all()

            for post in posts:
                try:
                    media_pk = cl.media_pk_from_code(post.instagram_media_id) \
                        if len(post.instagram_media_id) < 15 else int(post.instagram_media_id)
                    info = cl.media_info(media_pk)
                    post.ig_likes = info.like_count or 0
                    post.ig_comments = info.comment_count or 0
                    post.ig_views = getattr(info, "play_count", None) or getattr(info, "view_count", None) or 0
                    try:
                        ins = cl.media_insights(media_pk)
                        post.ig_saves = ins.get("saved", 0) or 0
                        post.ig_reach = ins.get("reach", 0) or 0
                    except Exception:
                        pass
                    post.insights_updated_at = now
                    updated += 1
                except Exception as e:
                    errors.append(str(e)[:80])

            db.session.commit()
        except Exception as e:
            errors.append(f"@{account.ig_username}: {str(e)[:80]}")

    return jsonify({
        "updated": updated,
        "errors": errors[:5],
        "ok": updated > 0 or not errors,
    })
