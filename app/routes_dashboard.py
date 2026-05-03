"""
Dashboard do cliente — todas as funcionalidades.
"""

import csv
import io
import json
import os
import random
import shutil
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, current_app, send_from_directory, jsonify, session,
)
from flask_login import login_required, current_user
from PIL import Image

from .models import db, InstagramAccount, PostQueue, CaptionTemplate, Client

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/selecionar-conta", methods=["GET", "POST"])
@login_required
def select_account():
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()
    if not accounts:
        return redirect(url_for("dashboard.index"))
    if len(accounts) == 1:
        session["active_account_id"] = accounts[0].id
        current_user.default_account_id = accounts[0].id
        db.session.commit()
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        acc_id = request.form.get("account_id", type=int)
        acc = next((a for a in accounts if a.id == acc_id), None)
        if acc:
            session["active_account_id"] = acc.id
            current_user.default_account_id = acc.id
            db.session.commit()
            flash(f"Conta @{acc.ig_username} selecionada como padrão.", "success")
        return redirect(url_for("dashboard.index"))
    return render_template("select_account.html", accounts=accounts)


@dashboard_bp.route("/api/set-active-account", methods=["POST"])
@login_required
def set_active_account():
    if request.is_json:
        acc_id = (request.get_json(silent=True) or {}).get("account_id")
    else:
        acc_id = request.form.get("account_id", type=int)
    acc = InstagramAccount.query.filter_by(id=acc_id, client_id=current_user.id).first()
    if acc:
        session["active_account_id"] = acc.id
        current_user.default_account_id = acc.id
        db.session.commit()
        return jsonify({"ok": True, "username": acc.ig_username})
    return jsonify({"ok": False}), 400


ALLOWED_IMG = {"jpg", "jpeg", "png", "webp"}
ALLOWED_VID = {"mp4", "mov"}
ALLOWED_ALL = ALLOWED_IMG | ALLOWED_VID

# ── Limites anti-bloqueio (Instagram / Facebook) ──────────
SAFE_LIMITS = {
    "max_posts_per_day": 2,         # Máximo de posts no feed por dia por plataforma
    "max_stories_per_day": 4,       # Máximo de stories por dia
    "min_interval_minutes": 240,    # Intervalo mínimo entre posts (4 horas)
    "random_delay_minutes": 20,     # Variação aleatória no horário (±minutos)
    "safe_hours_start": 8,          # Horário seguro início (8h)
    "safe_hours_end": 22,           # Horário seguro fim (22h)
    "suggested_times": [9, 17],     # Horários sugeridos: 9h e 17h
}


def _get_account_slots(account_id: int) -> tuple[list[str], list[str]]:
    """Retorna (weekday_slots, weekend_slots) da conta como listas de 'HH:MM'."""
    from .models import InstagramAccount as _IA
    acc = _IA.query.get(account_id)
    defaults_wd = ["09:00", "17:00"]
    defaults_we = ["10:30", "16:00"]
    if not acc:
        return defaults_wd, defaults_we
    try:
        wd = json.loads(acc.weekday_slots or "[]") or defaults_wd
    except Exception:
        wd = defaults_wd
    try:
        we = json.loads(acc.weekend_slots or "[]") or defaults_we
    except Exception:
        we = defaults_we
    return wd, we


def _next_free_slot(account_id: int, after: datetime) -> datetime:
    """
    Retorna o próximo slot livre (UTC naive) para a conta,
    usando os horários recorrentes configurados pelo usuário.
    'after' é UTC naive.
    """
    MAX_DAY = SAFE_LIMITS["max_posts_per_day"]
    weekday_slots, weekend_slots = _get_account_slots(account_id)

    # Converter 'after' para Brasil para comparar dias/horários
    after_br = after.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)

    # Buscar todos os scheduled_at já ocupados desta conta (pending)
    occupied = {
        p.scheduled_at for p in PostQueue.query.filter(
            PostQueue.account_id == account_id,
            PostQueue.status == "pending",
            PostQueue.scheduled_at.isnot(None),
        ).all()
        if p.scheduled_at
    }

    # Varrer até 14 dias à frente
    for day_offset in range(14):
        candidate_day_br = (after_br + timedelta(days=day_offset)).date()
        weekday = candidate_day_br.weekday()  # 0=Seg … 6=Dom
        slots = weekday_slots if weekday < 5 else weekend_slots

        # Contar posts já agendados nesse dia
        day_start_utc = datetime(candidate_day_br.year, candidate_day_br.month, candidate_day_br.day,
                                 0, 0, 0, tzinfo=BRAZIL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        day_end_utc = day_start_utc + timedelta(days=1)
        posts_day = PostQueue.query.filter(
            PostQueue.account_id == account_id,
            PostQueue.post_type != "story",
            PostQueue.status.in_(["pending", "posted", "processing"]),
            db.or_(
                db.and_(PostQueue.scheduled_at >= day_start_utc, PostQueue.scheduled_at < day_end_utc),
                db.and_(PostQueue.posted_at >= day_start_utc, PostQueue.posted_at < day_end_utc),
            ),
        ).count()

        if posts_day >= MAX_DAY:
            continue  # dia cheio, próximo

        # 1ª tentativa: slots configurados pelo usuário
        for slot_str in slots:
            h, m = map(int, slot_str.split(":"))
            slot_br = datetime(candidate_day_br.year, candidate_day_br.month, candidate_day_br.day,
                               h, m, 0, tzinfo=BRAZIL_TZ)
            slot_utc = slot_br.astimezone(timezone.utc).replace(tzinfo=None)

            if slot_utc <= after + timedelta(minutes=5):
                continue
            if slot_utc in occupied:
                continue

            return slot_utc

        # 2ª tentativa: dia tem capacidade mas slots configurados estão ocupados/passados.
        # Varre janelas de 30 min dentro do horário seguro para não jogar pro dia seguinte.
        safe_start = SAFE_LIMITS.get("safe_hours_start", 8)
        safe_end = SAFE_LIMITS.get("safe_hours_end", 22)
        for try_h in range(safe_start, safe_end):
            for try_m in (0, 30):
                slot_br = datetime(
                    candidate_day_br.year, candidate_day_br.month, candidate_day_br.day,
                    try_h, try_m, 0, tzinfo=BRAZIL_TZ,
                )
                slot_utc = slot_br.astimezone(timezone.utc).replace(tzinfo=None)
                if slot_utc <= after + timedelta(minutes=5):
                    continue
                if slot_utc in occupied:
                    continue
                return slot_utc

    # Fallback: amanhã às 9h
    fallback_br = (after_br + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return fallback_br.astimezone(timezone.utc).replace(tzinfo=None)


def _auto_schedule_posts(posts_to_schedule: list, account_id: int, client_id: int, start_time: datetime | None = None):
    """
    Distribui posts nos próximos slots recorrentes livres da conta.
    Se start_time fornecido, começa a busca a partir dele.
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    search_after = start_time if start_time else now_utc
    scheduled = 0

    for post in posts_to_schedule:
        slot = _next_free_slot(account_id, search_after)
        post.scheduled_at = slot
        scheduled += 1
        # Próxima busca começa após este slot
        search_after = slot

    return scheduled


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_ALL


def _is_video(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VID


def _apply_watermark(image_path: str, watermark_path: str, position: str, opacity: int) -> str:
    """Aplica watermark na imagem e salva sobrescrevendo."""
    try:
        base = Image.open(image_path).convert("RGBA")
        wm = Image.open(watermark_path).convert("RGBA")

        # Redimensionar watermark para 20% da largura da imagem
        wm_width = int(base.width * 0.2)
        wm_ratio = wm_width / wm.width
        wm_height = int(wm.height * wm_ratio)
        wm = wm.resize((wm_width, wm_height), Image.LANCZOS)

        # Aplicar opacidade
        alpha = wm.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity / 100))
        wm.putalpha(alpha)

        # Posição
        margin = 20
        positions = {
            "top-left": (margin, margin),
            "top-right": (base.width - wm_width - margin, margin),
            "bottom-left": (margin, base.height - wm_height - margin),
            "bottom-right": (base.width - wm_width - margin, base.height - wm_height - margin),
            "center": ((base.width - wm_width) // 2, (base.height - wm_height) // 2),
        }
        pos = positions.get(position, positions["bottom-right"])

        base.paste(wm, pos, wm)
        base = base.convert("RGB")
        base.save(image_path, quality=95)
        return image_path
    except Exception:
        return image_path


# ── Dashboard principal ──────────────────────────

@dashboard_bp.route("/dashboard")
@login_required
def index():
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()

    status_filter = request.args.get("status", "all")

    # Fila ativa: apenas posts NÃO postados (pending, draft, failed, processing)
    ACTIVE_STATUSES = ["pending", "draft", "failed", "processing"]
    queue_query = PostQueue.query.filter(
        PostQueue.client_id == current_user.id,
        PostQueue.status.in_(ACTIVE_STATUSES),
    )
    if status_filter not in ("all", "posted"):
        queue_query = queue_query.filter_by(status=status_filter)
    posts = queue_query.order_by(PostQueue.created_at.desc()).limit(100).all()

    # Histórico: posts publicados, agrupados por dia (Brasil), últimos 90 dias
    history_raw = (
        PostQueue.query.filter(
            PostQueue.client_id == current_user.id,
            PostQueue.status == "posted",
        )
        .order_by(PostQueue.posted_at.desc())
        .limit(200)
        .all()
    )
    _WEEKDAYS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    _MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

    # Agrupar por dia (horário Brasil)
    history_by_day: dict = {}
    for p in history_raw:
        ref = p.posted_at or p.scheduled_at or p.created_at
        if ref:
            ref_br = ref.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)
            day_key = ref_br.strftime("%d/%m/%Y")
            wd = _WEEKDAYS_PT[ref_br.weekday()]
            mo = _MONTHS_PT[ref_br.month - 1]
            day_label = f"{wd}, {ref_br.day:02d} de {mo} de {ref_br.year}"
        else:
            day_key = "—"
            day_label = "—"
        if day_key not in history_by_day:
            history_by_day[day_key] = {"label": day_label, "posts": []}
        history_by_day[day_key]["posts"].append(p)
    history_days = list(history_by_day.values())

    all_posts = PostQueue.query.filter_by(client_id=current_user.id)
    _now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    stats = {
        "total": all_posts.count(),
        "posted": all_posts.filter_by(status="posted").count(),
        "queued": all_posts.filter(
            PostQueue.status == "pending",
            db.or_(PostQueue.scheduled_at.is_(None), PostQueue.scheduled_at <= _now_utc)
        ).count(),
        "failed": all_posts.filter_by(status="failed").count(),
        "draft": all_posts.filter_by(status="draft").count(),
        "scheduled": all_posts.filter(PostQueue.scheduled_at > _now_utc, PostQueue.status == "pending").count(),
    }

    notifications = (
        PostQueue.query.filter_by(client_id=current_user.id, notified=False)
        .filter(PostQueue.status.in_(["posted", "failed"]))
        .order_by(PostQueue.posted_at.desc())
        .all()
    )

    templates = CaptionTemplate.query.filter_by(client_id=current_user.id).all()

    # Dados para calendário (posts agendados + postados)
    calendar_posts = (
        PostQueue.query.filter_by(client_id=current_user.id)
        .filter(PostQueue.status.in_(["pending", "posted", "draft"]))
        .all()
    )
    calendar_data = []
    for p in calendar_posts:
        date = p.scheduled_at or p.posted_at or p.created_at
        if date:
            calendar_data.append({
                "date": date.strftime("%Y-%m-%d"),
                "title": p.image_filename[:20],
                "status": p.status,
            })

    # Limite mensal
    plan_info = {
        "plan": "pro" if current_user.is_admin else current_user.plan,
        "used": current_user.posts_this_month or 0,
        "limit": current_user.get_monthly_limit(),
    }

    # Alertas de sessão expirando (>80 dias sem login)
    token_alerts = []
    for acc in accounts:
        if acc.last_login_at:
            last_login = acc.last_login_at if acc.last_login_at.tzinfo else acc.last_login_at.replace(tzinfo=timezone.utc)
            days_since = (datetime.now(timezone.utc) - last_login).days
            if days_since > 80:
                token_alerts.append({
                    "username": acc.ig_username,
                    "days": days_since,
                    "status": "critical" if days_since > 85 else "warning",
                })
                # Notificar via Telegram (apenas uma vez por dia — checa se não foi notificado hoje)
                if days_since in (81, 85, 89):  # Notifica nos dias 81, 85 e 89
                    try:
                        from modules.telegram_notify import notify_session_expiring
                        notify_session_expiring(current_user, acc, days_since)
                    except Exception:
                        pass

    # White label
    brand = {
        "name": current_user.brand_name or "Postay",
        "color": current_user.brand_color or "#7c5cff",
    }

    # ── Limites diários por conta ──
    now_brt = datetime.now(BRAZIL_TZ)
    today_start_brt = now_brt.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end_brt   = today_start_brt + timedelta(days=1)
    today_start = today_start_brt.astimezone(timezone.utc).replace(tzinfo=None)
    today_end   = today_end_brt.astimezone(timezone.utc).replace(tzinfo=None)

    daily_usage = {}
    MAX_DAY = SAFE_LIMITS["max_posts_per_day"]

    for acc in accounts:
        _feed_q = PostQueue.query.filter(
            PostQueue.account_id == acc.id,
            PostQueue.post_type != "story",
            PostQueue.status.in_(["posted", "pending", "processing"]),
            db.or_(
                db.and_(PostQueue.posted_at >= today_start, PostQueue.posted_at < today_end),
                db.and_(PostQueue.scheduled_at >= today_start, PostQueue.scheduled_at < today_end),
            ),
        )
        ig_today = _feed_q.filter(PostQueue.post_to_instagram == True).count()
        fb_today = _feed_q.filter(PostQueue.post_to_facebook == True).count()

        stories_today = PostQueue.query.filter(
            PostQueue.account_id == acc.id,
            PostQueue.post_type == "story",
            PostQueue.status.in_(["posted", "pending", "processing"]),
            db.or_(
                db.and_(PostQueue.posted_at >= today_start, PostQueue.posted_at < today_end),
                db.and_(PostQueue.scheduled_at >= today_start, PostQueue.scheduled_at < today_end),
            ),
        ).count()

        ig_remaining = max(0, MAX_DAY - ig_today)
        fb_remaining = max(0, MAX_DAY - fb_today)
        remaining_stories = max(0, SAFE_LIMITS["max_stories_per_day"] - stories_today)

        # Próximo horário sugerido disponível
        suggested = SAFE_LIMITS.get("suggested_times", [9, 17])
        next_available = None
        for h in sorted(suggested):
            candidate = now_brt.replace(hour=h, minute=0, second=0, microsecond=0)
            if candidate > now_brt + timedelta(minutes=10):
                next_available = candidate
                break
        if not next_available:
            next_available = (now_brt + timedelta(days=1)).replace(
                hour=suggested[0], minute=0, second=0, microsecond=0
            )

        daily_usage[acc.id] = {
            "username": acc.ig_username,
            "ig_used": ig_today,
            "ig_max": MAX_DAY,
            "ig_remaining": ig_remaining,
            "fb_used": fb_today,
            "fb_max": MAX_DAY,
            "fb_remaining": fb_remaining,
            "stories_used": stories_today,
            "stories_max": SAFE_LIMITS["max_stories_per_day"],
            "stories_remaining": remaining_stories,
            "next_available": next_available.strftime("%H:%M"),
            "next_available_day": "hoje" if next_available.date() == now_brt.date() else "amanhã",
            "ig_blocked": ig_remaining <= 0,
            "fb_blocked": fb_remaining <= 0,
            # legado para compatibilidade no template
            "feed_used": ig_today,
            "feed_max": MAX_DAY,
            "feed_remaining": ig_remaining,
            "blocked": ig_remaining <= 0,
        }

    import os as _os
    tiktok_configured = bool(_os.environ.get("TIKTOK_CLIENT_KEY", "").strip())

    active_account_id = session.get("active_account_id") or current_user.default_account_id

    return render_template(
        "dashboard.html",
        accounts=accounts,
        posts=posts,
        stats=stats,
        notifications=notifications,
        status_filter=status_filter,
        templates=templates,
        calendar_data=calendar_data,
        plan_info=plan_info,
        token_alerts=token_alerts,
        brand=brand,
        daily_usage=daily_usage,
        safe_limits=SAFE_LIMITS,
        history_days=history_days,
        tiktok_configured=tiktok_configured,
        active_account_id=active_account_id,
    )


@dashboard_bp.route("/notifications/dismiss", methods=["POST"])
@login_required
def dismiss_notifications():
    PostQueue.query.filter_by(client_id=current_user.id, notified=False).update({"notified": True})
    db.session.commit()
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    upload_folder = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    client_dir = os.path.realpath(os.path.join(upload_folder, str(current_user.id)))
    requested = os.path.realpath(os.path.join(upload_folder, filename))
    if not requested.startswith(client_dir + os.sep) and requested != client_dir:
        return "Acesso negado", 403
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


# ── Instagram (múltiplas contas) ─────────────────

@dashboard_bp.route("/instagram/connect", methods=["POST"])
@login_required
def connect_instagram():
    ig_username = request.form.get("ig_username", "").strip().lstrip("@")
    ig_password = request.form.get("ig_password", "")
    share_fb = request.form.get("share_facebook") == "on"
    label = request.form.get("label", "").strip() or ig_username

    if not ig_username or not ig_password:
        flash("Preencha usuário e senha.", "error")
        return redirect(url_for("dashboard.index"))

    # Plano Free: apenas 1 conta
    existing_count = InstagramAccount.query.filter_by(client_id=current_user.id).count()
    if existing_count >= current_user.max_accounts():
        already = InstagramAccount.query.filter_by(
            client_id=current_user.id, ig_username=ig_username
        ).first()
        if not already:
            flash(
                "Plano Free permite apenas 1 conta Instagram. "
                "Faça upgrade para o Plano Pro para adicionar mais contas.",
                "error",
            )
            return redirect(url_for("dashboard.index"))

    # Verificar se já existe essa conta
    existing = InstagramAccount.query.filter_by(
        client_id=current_user.id, ig_username=ig_username
    ).first()

    if existing:
        existing.set_ig_password(ig_password)
        existing.share_to_facebook = share_fb
        existing.label = label
        existing.status = "active"
        existing.status_message = None
    else:
        account = InstagramAccount(
            client_id=current_user.id,
            ig_username=ig_username,
            share_to_facebook=share_fb,
            label=label,
        )
        account.set_ig_password(ig_password)
        db.session.add(account)

    db.session.commit()
    flash(f"@{ig_username} conectado!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/instagram/connect-session", methods=["POST"])
@login_required
def connect_instagram_session():
    """Conecta conta do Instagram via Session ID (cookie). Funciona com qualquer conta."""
    session_id = request.form.get("session_id", "").strip()
    share_fb = request.form.get("share_facebook") == "on"

    if not session_id:
        flash("Cole o Session ID do Instagram.", "error")
        return redirect(url_for("dashboard.index"))

    # Plano Free: apenas 1 conta
    existing_count = InstagramAccount.query.filter_by(client_id=current_user.id).count()
    if existing_count >= current_user.max_accounts():
        flash("Plano Free permite apenas 1 conta. Faça upgrade para Pro.", "error")
        return redirect(url_for("dashboard.index"))

    # Validar o session_id tentando buscar o perfil
    from instagrapi import Client
    from pathlib import Path
    import json

    cl = Client()
    cl.delay_range = [2, 5]

    try:
        cl.login_by_sessionid(session_id)
        ig_username = cl.account_info().username
    except Exception as e:
        flash(f"Session ID inválido ou expirado: {e}", "error")
        return redirect(url_for("dashboard.index"))

    # Salvar ou atualizar conta
    existing = InstagramAccount.query.filter_by(
        client_id=current_user.id, ig_username=ig_username
    ).first()

    if existing:
        existing.share_to_facebook = share_fb
        existing.status = "active"
        existing.status_message = None
        account = existing
    else:
        account = InstagramAccount(
            client_id=current_user.id,
            ig_username=ig_username,
            share_to_facebook=share_fb,
            label=ig_username,
        )
        account.set_ig_password(session_id)  # Guarda session_id no campo de senha
        db.session.add(account)

    db.session.commit()

    # Salvar sessão para o worker usar
    session_file = Path(current_app.root_path).parent / "sessions" / f"account_{account.id}.json"
    cl.dump_settings(str(session_file))

    flash(f"@{ig_username} conectado via Session ID!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/instagram/<int:account_id>/disconnect", methods=["POST"])
@login_required
def disconnect_instagram(account_id):
    account = InstagramAccount.query.filter_by(id=account_id, client_id=current_user.id).first()
    if account:
        db.session.delete(account)
        db.session.commit()
        flash("Conta desconectada.", "info")
    return redirect(url_for("dashboard.index"))


# ── Upload (foto, álbum, vídeo/reels) ────────────

@dashboard_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "GET":
        return redirect(url_for("dashboard.index"))
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()
    if not accounts:
        flash("Conecte seu Instagram primeiro.", "error")
        return redirect(url_for("dashboard.index"))

    if not current_user.can_post():
        flash(f"Limite mensal atingido ({current_user.get_monthly_limit()} posts). Faça upgrade para o plano Pro!", "error")
        return redirect(url_for("dashboard.index"))

    files = request.files.getlist("photos")
    caption = request.form.get("caption", "").strip()
    hashtags = request.form.get("hashtags", "").strip()
    post_fb = request.form.get("share_facebook") == "on"
    post_story = request.form.get("post_story") == "on"
    post_tiktok = request.form.get("post_to_tiktok") == "on"

    # Stories apenas para Pro
    if post_story and not current_user.is_pro():
        flash("Stories é um recurso exclusivo do Plano Pro. Faça upgrade para usar!", "error")
        return redirect(url_for("dashboard.index"))
    account_id = request.form.get("account_id", type=int)
    scheduled_str = request.form.get("scheduled_at", "").strip()
    needs_approval = request.form.get("needs_approval") == "on"

    # Determinar qual conta usar: form > sessão ativa > primeira da lista
    if not account_id:
        account_id = session.get("active_account_id") or (current_user.default_account_id)
    if account_id:
        target_account = InstagramAccount.query.filter_by(
            id=account_id, client_id=current_user.id
        ).first()
    else:
        target_account = accounts[0]

    if not target_account:
        flash("Conta Instagram não encontrada.", "error")
        return redirect(url_for("dashboard.index"))

    # Parse scheduled_at — converte horário de Brasília para UTC (naive) para comparar com o worker
    scheduled_at = None
    if scheduled_str:
        try:
            local_dt = datetime.strptime(scheduled_str, "%Y-%m-%dT%H:%M")
            scheduled_at = local_dt.replace(tzinfo=BRAZIL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            flash("Data/hora inválida.", "error")
            return redirect(url_for("dashboard.index"))

    # ── Verificar limite diário por plataforma ──────────────────
    # Usa horário de Brasília (BRT) para definir o "dia" — evita que posts
    # agendados após 21h BRT (= meia-noite UTC) caiam no dia seguinte.
    if scheduled_at:
        ref_brt = scheduled_at.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)
    else:
        ref_brt = datetime.now(BRAZIL_TZ)
    day_start_brt = ref_brt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_brt   = day_start_brt + timedelta(days=1)
    day_start = day_start_brt.astimezone(timezone.utc).replace(tzinfo=None)
    day_end   = day_end_brt.astimezone(timezone.utc).replace(tzinfo=None)

    _feed_base = PostQueue.query.filter(
        PostQueue.account_id == target_account.id,
        PostQueue.post_type != "story",
        PostQueue.status.in_(["posted", "pending", "processing"]),
        db.or_(
            db.and_(PostQueue.posted_at >= day_start, PostQueue.posted_at < day_end),
            db.and_(PostQueue.scheduled_at >= day_start, PostQueue.scheduled_at < day_end),
        ),
    )

    ig_today = _feed_base.filter(PostQueue.post_to_instagram == True).count()
    fb_today = _feed_base.filter(PostQueue.post_to_facebook == True).count()

    stories_today = PostQueue.query.filter(
        PostQueue.account_id == target_account.id,
        PostQueue.post_type == "story",
        PostQueue.status.in_(["posted", "pending", "processing"]),
        db.or_(
            db.and_(PostQueue.posted_at >= day_start, PostQueue.posted_at < day_end),
            db.and_(PostQueue.scheduled_at >= day_start, PostQueue.scheduled_at < day_end),
        ),
    ).count()

    MAX_DAY = SAFE_LIMITS["max_posts_per_day"]

    day_label = ref_brt.strftime("%d/%m")
    # Se o dia escolhido está cheio, mover automaticamente para o próximo slot livre
    if not post_story and (ig_today >= MAX_DAY or (post_fb and fb_today >= MAX_DAY)):
        search_after = day_start  # UTC naive — começa a buscar a partir deste dia
        new_slot = _next_free_slot(target_account.id, search_after)
        new_slot_brt = new_slot.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)
        flash(
            f"Dia {day_label} já tem {MAX_DAY}/{MAX_DAY} posts. "
            f"Agendamento movido automaticamente para {new_slot_brt.strftime('%d/%m às %H:%M')}.",
            "info",
        )
        scheduled_at = new_slot
        # Recalcular ref_brt para o novo dia (usado abaixo na flash de confirmação)
        ref_brt = new_slot_brt

    if post_story and stories_today >= SAFE_LIMITS["max_stories_per_day"]:
        flash(
            f"Limite de stories atingido para @{target_account.ig_username} "
            f"({SAFE_LIMITS['max_stories_per_day']} stories/dia). "
            f"Tente novamente amanhã.",
            "error",
        )
        return redirect(url_for("dashboard.index"))

    if not files or all(f.filename == "" for f in files):
        flash("Selecione pelo menos uma foto.", "error")
        return redirect(url_for("dashboard.index"))

    client_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(current_user.id))
    os.makedirs(client_dir, exist_ok=True)

    # Verificar se é álbum (múltiplas fotos) ou vídeo
    valid_files = [f for f in files if f.filename and _allowed_file(f.filename)]

    if not valid_files:
        flash("Nenhum arquivo válido selecionado.", "error")
        return redirect(url_for("dashboard.index"))

    is_album = len(valid_files) > 1 and all(not _is_video(f.filename) for f in valid_files)
    is_reels = len(valid_files) == 1 and _is_video(valid_files[0].filename)

    if is_album:
        # Álbum/Carrossel
        paths = []
        names = []
        for file in valid_files:
            ext = file.filename.rsplit(".", 1)[1].lower()
            safe_name = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(client_dir, safe_name)
            file.save(file_path)

            # Watermark
            if current_user.watermark_enabled and current_user.watermark_path:
                _apply_watermark(file_path, current_user.watermark_path,
                                 current_user.watermark_position, current_user.watermark_opacity)

            paths.append(file_path)
            names.append(file.filename)

        post = PostQueue(
            client_id=current_user.id,
            account_id=target_account.id,
            post_type="album",
            image_path="|".join(paths),
            image_filename=", ".join(names),
            caption=caption if caption else None,
            hashtags=hashtags,
            scheduled_at=scheduled_at,
            needs_approval=needs_approval,
            status="draft" if needs_approval else "pending",
            post_to_instagram=True,
            post_to_facebook=post_fb,
            post_to_tiktok=post_tiktok,
        )
        db.session.add(post)
        queued = 1

    else:
        # Posts individuais (fotos ou 1 vídeo)
        queued = 0
        for file in valid_files:
            ext = file.filename.rsplit(".", 1)[1].lower()
            safe_name = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(client_dir, safe_name)
            file.save(file_path)

            post_type = "reels" if _is_video(file.filename) else "photo"

            # Watermark (apenas fotos)
            if post_type == "photo" and current_user.watermark_enabled and current_user.watermark_path:
                _apply_watermark(file_path, current_user.watermark_path,
                                 current_user.watermark_position, current_user.watermark_opacity)

            post = PostQueue(
                client_id=current_user.id,
                account_id=target_account.id,
                post_type=post_type,
                image_path=file_path,
                image_filename=file.filename,
                caption=caption if caption else None,
                hashtags=hashtags,
                scheduled_at=scheduled_at,
                needs_approval=needs_approval,
                status="draft" if needs_approval else "pending",
                post_to_instagram=True,
                post_to_facebook=post_fb,
            )
            db.session.add(post)
            queued += 1

    # Se marcou "Postar também nos Stories", criar cópia com post_type=story
    if post_story:
        story_posts = PostQueue.query.filter_by(client_id=current_user.id).order_by(PostQueue.id.desc()).limit(queued).all()
        for sp in story_posts:
            # Copiar arquivo para o story
            story_paths = []
            for path in sp.image_path.split("|"):
                if os.path.exists(path):
                    ext = path.rsplit(".", 1)[1] if "." in path else "jpg"
                    story_name = f"{uuid.uuid4().hex}.{ext}"
                    story_path = os.path.join(client_dir, story_name)
                    shutil.copy2(path, story_path)
                    story_paths.append(story_path)

            if story_paths:
                story = PostQueue(
                    client_id=current_user.id,
                    account_id=target_account.id,
                    post_type="story",
                    image_path=story_paths[0],
                    image_filename=f"[Story] {sp.image_filename}",
                    caption=None,
                    status="pending",
                    post_to_instagram=True,
                    post_to_facebook=post_fb,
                )
                db.session.add(story)
                queued += 1

    db.session.commit()

    # ── Agendamento ──
    if not needs_approval:
        new_posts = (
            PostQueue.query.filter_by(client_id=current_user.id, status="pending")
            .order_by(PostQueue.id.desc())
            .limit(queued)
            .all()
        )
        new_posts.reverse()

        if scheduled_at:
            # Usuário escolheu horário específico — usar exatamente o horário informado
            for p in new_posts:
                p.scheduled_at = scheduled_at
            db.session.commit()
            times_str = scheduled_at.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ).strftime("%d/%m %H:%M")
            flash(f"{len(new_posts)} postagem(ns) agendada(s) para {times_str}.", "success")
        else:
            # "Agora" — deixa scheduled_at=None, worker posta na próxima rodada (até 5 min)
            flash(f"{queued} postagem(ns) na fila! Será publicada em até 5 minutos.", "success")
    else:
        flash(f"{queued} postagem(ns) salvas como rascunho. Aprove a legenda para publicar.", "info")

    return redirect(url_for("dashboard.index"))


# ── Gerenciar posts ──────────────────────────────

@dashboard_bp.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if post:
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                os.remove(path)
        db.session.delete(post)
        db.session.commit()
        flash("Postagem removida.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/edit", methods=["POST"])
@login_required
def edit_post(post_id):
    """Edita legenda, hashtags e horário de um post. Posts já publicados geram um novo agendamento."""
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if not post or post.status not in ("pending", "draft", "failed", "posted"):
        flash("Post não encontrado ou não pode ser editado.", "error")
        return redirect(url_for("dashboard.index"))

    new_caption = request.form.get("caption", "").strip() or None
    new_hashtags = request.form.get("hashtags", "").strip() or None
    scheduled_str = request.form.get("scheduled_at", "").strip()
    new_scheduled = None
    if scheduled_str:
        try:
            local_dt = datetime.strptime(scheduled_str, "%Y-%m-%dT%H:%M")
            new_scheduled = local_dt.replace(tzinfo=BRAZIL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            pass

    if post.status == "posted":
        # Post já publicado → criar novo agendamento sem alterar o histórico
        if not current_user.can_post():
            flash("Limite mensal atingido.", "error")
            return redirect(url_for("dashboard.index"))

        # Copiar arquivos para que uma futura limpeza do histórico não apague os originais
        new_paths = []
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                ext = path.rsplit(".", 1)[1] if "." in path else "jpg"
                new_path = os.path.join(os.path.dirname(path), f"{uuid.uuid4().hex}.{ext}")
                shutil.copy2(path, new_path)
                new_paths.append(new_path)

        if not new_paths:
            flash("Arquivos originais não encontrados. Faça upload novamente.", "error")
            return redirect(url_for("dashboard.index"))

        new_post = PostQueue(
            client_id=current_user.id,
            account_id=post.account_id,
            post_type=post.post_type,
            image_path="|".join(new_paths),
            image_filename=post.image_filename,
            caption=new_caption if new_caption is not None else post.caption,
            hashtags=new_hashtags if new_hashtags is not None else post.hashtags,
            scheduled_at=new_scheduled,
            status="pending",
            post_to_instagram=post.post_to_instagram,
            post_to_facebook=post.post_to_facebook,
        )
        db.session.add(new_post)
        db.session.commit()
        when = new_scheduled.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ).strftime("%d/%m às %H:%M") if new_scheduled else "agora (até 5 min)"
        flash(f"Postagem reagendada para {when}!", "success")
    else:
        # Post pendente/rascunho/falhou → editar no lugar
        post.caption = new_caption
        post.hashtags = new_hashtags
        post.scheduled_at = new_scheduled

        if post.status == "failed":
            post.status = "pending"
            post.error_message = None

        db.session.commit()
        flash("Post atualizado!", "success")

    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/approve", methods=["POST"])
@login_required
def approve_post(post_id):
    """Aprova um rascunho — muda status para pending."""
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id, status="draft").first()
    if post:
        new_caption = request.form.get("caption", "").strip()
        if new_caption:
            post.caption = new_caption
        post.status = "pending"
        post.needs_approval = False
        db.session.commit()
        flash("Postagem aprovada e enviada para a fila!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/retry", methods=["POST"])
@login_required
def retry_post(post_id):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id, status="failed").first()
    if post:
        post.status = "pending"
        post.error_message = None
        db.session.commit()
        flash("Postagem reenviada para a fila.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/duplicate", methods=["POST"])
@login_required
def duplicate_post(post_id):
    """Duplica um post existente (postar de novo)."""
    original = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if not original:
        flash("Postagem não encontrada.", "error")
        return redirect(url_for("dashboard.index"))

    if not current_user.can_post():
        flash("Limite mensal atingido.", "error")
        return redirect(url_for("dashboard.index"))

    # Copiar arquivos para evitar conflito se o original for deletado
    new_paths = []
    for path in original.image_path.split("|"):
        if os.path.exists(path):
            ext = path.rsplit(".", 1)[1] if "." in path else "jpg"
            new_name = f"{uuid.uuid4().hex}.{ext}"
            new_path = os.path.join(os.path.dirname(path), new_name)
            shutil.copy2(path, new_path)
            new_paths.append(new_path)

    if not new_paths:
        flash("Arquivos originais não encontrados.", "error")
        return redirect(url_for("dashboard.index"))

    duplicate = PostQueue(
        client_id=current_user.id,
        account_id=original.account_id,
        post_type=original.post_type,
        image_path="|".join(new_paths),
        image_filename=original.image_filename,
        caption=original.caption,
        hashtags=original.hashtags,
        status="pending",
        post_to_instagram=original.post_to_instagram,
        post_to_facebook=original.post_to_facebook,
    )
    db.session.add(duplicate)
    db.session.commit()
    flash("Postagem duplicada e enviada para a fila!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/posts/clear-posted", methods=["POST"])
@login_required
def clear_posted():
    posted = PostQueue.query.filter_by(client_id=current_user.id, status="posted").all()
    count = 0
    for post in posted:
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                os.remove(path)
        db.session.delete(post)
        count += 1
    db.session.commit()
    if count:
        flash(f"{count} postagens publicadas removidas.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/posts/clear-failed", methods=["POST"])
@login_required
def clear_failed():
    failed = PostQueue.query.filter_by(client_id=current_user.id, status="failed").all()
    count = 0
    for post in failed:
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                os.remove(path)
        db.session.delete(post)
        count += 1
    db.session.commit()
    if count:
        flash(f"{count} postagens com erro removidas.", "info")
    return redirect(url_for("dashboard.index"))


# ── Templates de legenda ─────────────────────────

@dashboard_bp.route("/templates/save", methods=["POST"])
@login_required
def save_template():
    name = request.form.get("template_name", "").strip()
    content = request.form.get("template_content", "").strip()
    hashtags = request.form.get("template_hashtags", "").strip()

    if not name or not content:
        flash("Preencha nome e conteúdo do template.", "error")
        return redirect(url_for("dashboard.index"))

    template = CaptionTemplate(
        client_id=current_user.id,
        name=name,
        content=content,
        hashtags=hashtags,
    )
    db.session.add(template)
    db.session.commit()
    flash(f"Template '{name}' salvo!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def delete_template(template_id):
    template = CaptionTemplate.query.filter_by(id=template_id, client_id=current_user.id).first()
    if template:
        db.session.delete(template)
        db.session.commit()
        flash("Template removido.", "info")
    return redirect(url_for("dashboard.index"))


# ── Watermark ────────────────────────────────────

@dashboard_bp.route("/watermark", methods=["POST"])
@login_required
def update_watermark():
    file = request.files.get("watermark_file")
    current_user.watermark_enabled = request.form.get("watermark_enabled") == "on"
    current_user.watermark_position = request.form.get("watermark_position", "bottom-right")
    try:
        current_user.watermark_opacity = max(0, min(100, int(request.form.get("watermark_opacity", 80))))
    except (ValueError, TypeError):
        current_user.watermark_opacity = 80

    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[1].lower()
        if ext in {"png", "jpg", "jpeg", "webp"}:
            wm_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(current_user.id), "watermarks")
            os.makedirs(wm_dir, exist_ok=True)
            wm_path = os.path.join(wm_dir, f"watermark.{ext}")
            file.save(wm_path)
            current_user.watermark_path = wm_path

    db.session.commit()
    flash("Configuração de watermark atualizada!", "success")
    return redirect(url_for("dashboard.index"))


# ── API ──────────────────────────────────────────

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
    """Retorna agendamentos dos próximos 7 dias a partir de hoje."""
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
    """Gera 3 opções de legenda via IA (AJAX)."""
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


@dashboard_bp.route("/csv-import", methods=["POST"])
@login_required
def csv_import():
    """Importa postagens em massa via CSV (colunas: filename, caption, hashtags, scheduled_at)."""
    if not current_user.is_pro():
        flash("Import CSV é um recurso exclusivo do Plano Pro. Faça upgrade para usar!", "error")
        return redirect(url_for("dashboard.index"))

    accounts = InstagramAccount.query.filter_by(client_id=current_user.id, status="active").all()
    if not accounts:
        flash("Conecte seu Instagram primeiro.", "error")
        return redirect(url_for("dashboard.index"))

    csv_file = request.files.get("csv_file")
    images = request.files.getlist("csv_images")

    if not csv_file or not csv_file.filename:
        flash("Selecione um arquivo CSV.", "error")
        return redirect(url_for("dashboard.index"))

    account_id = request.form.get("account_id", type=int) or accounts[0].id

    # Salvar imagens enviadas juntas
    client_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(current_user.id))
    os.makedirs(client_dir, exist_ok=True)

    image_map = {}
    for img in images:
        if img.filename and _allowed_file(img.filename):
            ext = img.filename.rsplit(".", 1)[1].lower() if "." in img.filename else "jpg"
            safe_name = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(client_dir, safe_name)
            img.save(file_path)
            image_map[img.filename.lower()] = file_path

    # Parse CSV
    try:
        content = csv_file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
    except Exception:
        flash("Erro ao ler CSV. Use UTF-8 com colunas: filename, caption, hashtags, scheduled_at", "error")
        return redirect(url_for("dashboard.index"))

    queued = 0
    for row in reader:
        filename = (row.get("filename") or "").strip()
        if not filename:
            continue

        file_path = image_map.get(filename.lower())
        if not file_path:
            continue

        if not current_user.can_post():
            flash(f"Limite mensal atingido. {queued} postagens importadas.", "error")
            break

        scheduled_at = None
        sched_str = (row.get("scheduled_at") or "").strip()
        if sched_str:
            try:
                scheduled_at = datetime.strptime(sched_str, "%Y-%m-%d %H:%M")
            except ValueError:
                pass

        is_video = filename.rsplit(".", 1)[1].lower() in ALLOWED_VID if "." in filename else False

        post = PostQueue(
            client_id=current_user.id,
            account_id=account_id,
            post_type="reels" if is_video else "photo",
            image_path=file_path,
            image_filename=filename,
            caption=(row.get("caption") or "").strip() or None,
            hashtags=(row.get("hashtags") or "").strip() or None,
            scheduled_at=scheduled_at,
            status="pending",
            post_to_instagram=True,
            post_to_facebook=True,
        )
        db.session.add(post)
        queued += 1

    db.session.commit()
    flash(f"{queued} postagens importadas do CSV!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/api/telegram-config", methods=["POST"])
@login_required
def save_telegram_config():
    """Salva token e chat_id do Telegram."""
    data = request.get_json()
    current_user.telegram_bot_token = data.get("bot_token", "").strip() or None
    current_user.telegram_chat_id = data.get("chat_id", "").strip() or None
    db.session.commit()
    # Testar conexão
    if current_user.telegram_bot_token and current_user.telegram_chat_id:
        from modules.telegram_notify import send_telegram
        ok = send_telegram(current_user.telegram_bot_token, current_user.telegram_chat_id,
                           "✅ <b>Postay conectado!</b>\nVocê receberá alertas aqui.")
        return jsonify({"ok": True, "tested": ok})
    return jsonify({"ok": True, "tested": False})


@dashboard_bp.route("/api/account-slots")
@login_required
def get_account_slots():
    """Retorna os slots recorrentes configurados de uma conta."""
    account_id = request.args.get("account_id", type=int)
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()
    if account_id:
        account = next((a for a in accounts if a.id == account_id), None)
    else:
        account = accounts[0] if accounts else None
    if not account:
        return jsonify({"weekday_slots": ["09:00", "17:00"], "weekend_slots": ["10:30", "16:00"]})
    try:
        wd = json.loads(account.weekday_slots or "[]") or ["09:00", "17:00"]
    except Exception:
        wd = ["09:00", "17:00"]
    try:
        we = json.loads(account.weekend_slots or "[]") or ["10:30", "16:00"]
    except Exception:
        we = ["10:30", "16:00"]
    return jsonify({"weekday_slots": wd, "weekend_slots": we})


@dashboard_bp.route("/api/schedule-slots", methods=["POST"])
@login_required
def save_schedule_slots():
    """Salva os slots recorrentes de uma conta."""
    data = request.get_json()
    account_id = data.get("account_id")
    weekday = data.get("weekday_slots", [])
    weekend = data.get("weekend_slots", [])

    account = InstagramAccount.query.filter_by(id=account_id, client_id=current_user.id).first()
    if not account:
        return jsonify({"error": "Conta não encontrada"}), 404

    # Validar formato HH:MM
    import re
    pattern = re.compile(r"^\d{2}:\d{2}$")
    weekday = [s for s in weekday if pattern.match(s)][:2]
    weekend = [s for s in weekend if pattern.match(s)][:2]

    account.weekday_slots = json.dumps(weekday if weekday else ["09:00", "17:00"])
    account.weekend_slots = json.dumps(weekend if weekend else ["10:30", "16:00"])
    db.session.commit()
    return jsonify({"ok": True})


@dashboard_bp.route("/whitelabel", methods=["POST"])
@login_required
def update_whitelabel():
    """Salva configurações de white label."""
    if not current_user.is_pro():
        flash("White Label é um recurso exclusivo do Plano Pro. Faça upgrade para usar!", "error")
        return redirect(url_for("dashboard.index"))

    brand_name = request.form.get("brand_name", "").strip()
    brand_color = request.form.get("brand_color", "").strip()

    import re as _re
    if brand_name:
        current_user.brand_name = brand_name
    if brand_color and _re.match(r'^#[0-9a-fA-F]{6}$', brand_color):
        current_user.brand_color = brand_color

    db.session.commit()
    flash("Configuração de marca atualizada!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/api/post-metrics/<int:post_id>")
@login_required
def api_post_metrics(post_id):
    """Retorna métricas de um post (likes, comentários, views)."""
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if not post or not post.instagram_media_id:
        return jsonify({"error": "Post sem métricas disponíveis"}), 404

    account = InstagramAccount.query.filter_by(
        id=post.account_id, client_id=current_user.id
    ).first()
    if not account:
        return jsonify({"error": "Conta não encontrada"}), 404

    from modules.metrics import fetch_post_metrics
    from pathlib import Path

    session_dir = str(Path(current_app.root_path).parent / "sessions")
    metrics = fetch_post_metrics(account, post.instagram_media_id, session_dir)

    if metrics:
        return jsonify(metrics)
    return jsonify({"error": "Não foi possível buscar métricas"}), 500


@dashboard_bp.route("/api/best-time", methods=["POST"])
@login_required
def api_best_time():
    """Sugere melhor horário para postar baseado em IA."""
    from modules.caption_generator import CaptionGenerator
    from modules.logger import setup_global_logger

    logger = setup_global_logger(".")
    gen = CaptionGenerator(logger, provider="groq")

    if not gen.client:
        return jsonify({"suggestion": "Melhores horários gerais: 8h-9h, 12h-13h, 18h-20h"})

    # Buscar histórico do cliente
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


@dashboard_bp.route("/gdrive-import", methods=["POST"])
@login_required
def gdrive_import():
    """Importa fotos de uma pasta do Google Drive e agenda por dia da semana."""
    if not current_user.is_pro():
        flash("Import do Google Drive é um recurso exclusivo do Plano Pro. Faça upgrade para usar!", "error")
        return redirect(url_for("dashboard.index"))

    from modules.gdrive_import import sync_drive

    accounts = InstagramAccount.query.filter_by(client_id=current_user.id, status="active").all()
    if not accounts:
        flash("Conecte seu Instagram primeiro.", "error")
        return redirect(url_for("dashboard.index"))

    folder_id = current_user.gdrive_folder_id or ""
    if not folder_id:
        flash("Configure primeiro a URL da sua pasta do Google Drive nas configurações.", "error")
        return redirect(url_for("dashboard.index"))

    # Baixa fotos novas + lê postagens.txt em uma única operação
    imported, captions_by_day = sync_drive(current_user.id, current_app.config["UPLOAD_FOLDER"], folder_id)

    if not imported:
        flash("Nenhuma nova imagem encontrada no Google Drive.", "info")
        return redirect(url_for("dashboard.index"))

    account_id = accounts[0].id

    # Calcular a próxima segunda-feira (ou a semana atual)
    now = datetime.now(timezone.utc)
    today_weekday = now.weekday()  # 0=segunda, 6=domingo
    # Se já passou de segunda, usar a próxima semana
    days_until_monday = (7 - today_weekday) % 7
    if days_until_monday == 0:
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        week_start = (now + timedelta(days=days_until_monday)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Horários sugeridos por slot (1º post = 9h, 2º post = 17h)
    slot_hours = SAFE_LIMITS.get("suggested_times", [9, 17])

    # Contar posts já agendados por dia nesta semana (para não ultrapassar o limite)
    posts_per_day: dict[int, int] = {i: 0 for i in range(7)}  # {weekday: count}
    existing = PostQueue.query.filter(
        PostQueue.client_id == current_user.id,
        PostQueue.status.in_(["pending", "draft", "processing"]),
        PostQueue.scheduled_at >= week_start,
        PostQueue.scheduled_at < week_start + timedelta(days=7),
    ).all()
    for ep in existing:
        if ep.scheduled_at:
            wd = ep.scheduled_at.weekday()
            posts_per_day[wd] = posts_per_day.get(wd, 0) + 1

    # Se não há dia identificado pelo nome do arquivo, distribuir em ordem (segunda → domingo)
    files_without_day = [item for item in imported if item.get("weekday") is None]
    files_with_day = [item for item in imported if item.get("weekday") is not None]

    # Atribuir dias aos arquivos sem dia detectado (preenche dias disponíveis na ordem)
    next_day = 0
    for item in files_without_day:
        while next_day < 7 and posts_per_day.get(next_day, 0) >= len(slot_hours):
            next_day += 1
        if next_day < 7:
            item["weekday"] = next_day
            next_day += 1

    all_items = files_with_day + files_without_day
    created_count = 0
    skipped_count = 0

    for item in all_items:
        weekday = item.get("weekday")
        if weekday is None:
            skipped_count += 1
            continue  # Sem dia disponível

        day_count = posts_per_day.get(weekday, 0)
        if day_count >= len(slot_hours):
            skipped_count += 1
            continue  # Dia cheio para esta semana

        if not current_user.can_post():
            flash("Limite mensal atingido.", "error")
            break

        # Calcular horário agendado
        # Usar horários do postagens.txt se disponível, senão usar padrão (9h/17h)
        day_hours = captions_by_day.get(weekday, {}).get("hours") or slot_hours
        slot_hour = day_hours[day_count % len(day_hours)]
        jitter = random.randint(-SAFE_LIMITS.get("random_delay_minutes", 20),
                                SAFE_LIMITS.get("random_delay_minutes", 20))
        sched_time = (week_start + timedelta(days=weekday)).replace(
            hour=slot_hour, minute=0, second=0, microsecond=0
        ) + timedelta(minutes=jitter)

        # Legenda do dia (do postagens.txt)
        day_caption_data = captions_by_day.get(weekday, {})
        caption = day_caption_data.get("caption", "")
        hashtags = day_caption_data.get("hashtags", "")

        post = PostQueue(
            client_id=current_user.id,
            account_id=account_id,
            post_type="photo",
            image_path=item["filepath"],
            image_filename=item["filename"],
            caption=caption,
            hashtags=hashtags,
            scheduled_at=sched_time,
            status="pending",
            needs_approval=False,
            post_to_instagram=True,
            post_to_facebook=True,
        )
        db.session.add(post)
        current_user.increment_post_count()
        posts_per_day[weekday] = day_count + 1
        created_count += 1

    db.session.commit()

    day_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    caption_info = f" com legendas do postagens.txt" if captions_by_day else " (sem postagens.txt — sem legendas)"
    msg = f"{created_count} post(s) agendados para a semana{caption_info}."
    if skipped_count:
        msg += f" {skipped_count} ignorado(s) (dia cheio ou sem dia disponível)."
    flash(msg, "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/gdrive/save-folder", methods=["POST"])
@login_required
def save_gdrive_folder():
    """Salva o ID/URL da pasta do Google Drive do cliente."""
    folder_url = request.form.get("gdrive_folder_url", "").strip()

    from modules.gdrive_import import extract_folder_id
    folder_id = extract_folder_id(folder_url)

    if folder_url and not folder_id:
        flash("URL ou ID da pasta inválido. Cole o link completo da pasta do Google Drive.", "error")
        return redirect(url_for("dashboard.index"))

    current_user.gdrive_folder_id = folder_id or None
    db.session.commit()

    if folder_id:
        flash("Pasta do Google Drive configurada com sucesso!", "success")
    else:
        flash("Configuração do Google Drive removida.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/gdrive/list-files")
@login_required
def gdrive_list_files():
    """Retorna JSON com lista de arquivos na pasta do Drive configurada."""
    if not current_user.is_pro():
        return jsonify({"error": "Recurso Pro"}), 403

    folder_id = current_user.gdrive_folder_id or ""
    if not folder_id:
        return jsonify({"files": [], "error": "Pasta não configurada"})

    from modules.gdrive_import import list_drive_files
    files = list_drive_files(folder_id)
    return jsonify({"files": files})


# ── Mini Dashboard de Estatísticas ──────────────

@dashboard_bp.route("/stats")
@login_required
def stats_page():
    """Página dedicada de estatísticas e métricas do cliente."""
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()

    now = datetime.now(timezone.utc)
    now_brt = datetime.now(BRAZIL_TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    all_posts = PostQueue.query.filter_by(client_id=current_user.id)

    stats = {
        "total": all_posts.count(),
        "posted": all_posts.filter_by(status="posted").count(),
        "pending": all_posts.filter_by(status="pending").count(),
        "failed": all_posts.filter_by(status="failed").count(),
        "today": all_posts.filter(PostQueue.status == "posted", PostQueue.posted_at >= today_start).count(),
        "this_week": all_posts.filter(PostQueue.status == "posted", PostQueue.posted_at >= week_ago).count(),
        "this_month": all_posts.filter(PostQueue.status == "posted", PostQueue.posted_at >= month_ago).count(),
    }

    # Gráfico: posts por dia nos últimos 14 dias
    daily_chart = []
    for i in range(13, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = PostQueue.query.filter(
            PostQueue.client_id == current_user.id,
            PostQueue.status == "posted",
            PostQueue.posted_at >= day_start,
            PostQueue.posted_at < day_end,
        ).count()
        daily_chart.append({"day": day.strftime("%d/%m"), "count": count})

    # Posts por tipo
    by_type = {}
    for ptype in ["photo", "album", "reels", "story"]:
        by_type[ptype] = all_posts.filter_by(post_type=ptype, status="posted").count()

    # Taxa de sucesso
    total_attempted = stats["posted"] + stats["failed"]
    success_rate = round((stats["posted"] / total_attempted * 100) if total_attempted > 0 else 0)

    # Horários mais postados (top 5) — em BRT
    posted_list = (
        PostQueue.query.filter_by(client_id=current_user.id, status="posted")
        .filter(PostQueue.posted_at.isnot(None))
        .all()
    )
    hour_counts: dict[int, int] = {}
    for p in posted_list:
        h_brt = p.posted_at.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ).hour
        hour_counts[h_brt] = hour_counts.get(h_brt, 0) + 1
    top_hours = sorted(hour_counts.items(), key=lambda x: -x[1])[:5]

    # Posts agendados futuros
    scheduled_upcoming = (
        PostQueue.query.filter(
            PostQueue.client_id == current_user.id,
            PostQueue.status == "pending",
            PostQueue.scheduled_at.isnot(None),
            PostQueue.scheduled_at > now,
        )
        .order_by(PostQueue.scheduled_at)
        .limit(10)
        .all()
    )

    # ── Engajamento semanal (Instagram) ───────────────────────────────
    week_posts = (
        PostQueue.query.filter(
            PostQueue.client_id == current_user.id,
            PostQueue.status == "posted",
            PostQueue.posted_at >= week_ago,
            PostQueue.instagram_media_id.isnot(None),
        )
        .order_by(PostQueue.posted_at.desc())
        .all()
    )

    engagement = {
        "total_likes": sum((p.ig_likes or 0) for p in week_posts),
        "total_comments": sum((p.ig_comments or 0) for p in week_posts),
        "total_views": sum((p.ig_views or 0) for p in week_posts),
        "total_saves": sum((p.ig_saves or 0) for p in week_posts),
        "total_reach": sum((p.ig_reach or 0) for p in week_posts),
        "posts_with_data": sum(1 for p in week_posts if (p.ig_likes or 0) > 0),
        "posts_count": len(week_posts),
    }
    total_interactions = engagement["total_likes"] + engagement["total_comments"]
    engagement["engagement_rate"] = round(
        (total_interactions / engagement["total_reach"] * 100)
        if engagement["total_reach"] > 0 else 0, 2
    )

    # Top post da semana
    top_post = max(week_posts, key=lambda p: (p.ig_likes or 0) + (p.ig_comments or 0), default=None)

    # Gráfico de engajamento diário (7 dias)
    engagement_chart = []
    for i in range(6, -1, -1):
        day_brt = (now_brt - timedelta(days=i)).date()
        day_start_utc = datetime(day_brt.year, day_brt.month, day_brt.day,
                                 tzinfo=BRAZIL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        day_end_utc = day_start_utc + timedelta(days=1)
        day_posts = [p for p in week_posts
                     if p.posted_at and day_start_utc <= p.posted_at < day_end_utc]
        engagement_chart.append({
            "day": day_brt.strftime("%d/%m"),
            "likes": sum((p.ig_likes or 0) for p in day_posts),
            "comments": sum((p.ig_comments or 0) for p in day_posts),
            "posts": len(day_posts),
        })

    # Limites anti-bloqueio ativos
    safe_info = dict(SAFE_LIMITS)

    brand = {
        "name": current_user.brand_name or "Postay",
        "color": current_user.brand_color or "#7c5cff",
    }

    return render_template(
        "stats.html",
        accounts=accounts,
        stats=stats,
        daily_chart=daily_chart,
        by_type=by_type,
        success_rate=success_rate,
        top_hours=top_hours,
        scheduled_upcoming=scheduled_upcoming,
        safe_info=safe_info,
        brand=brand,
        engagement=engagement,
        engagement_chart=engagement_chart,
        week_posts=week_posts,
        top_post=top_post,
    )


@dashboard_bp.route("/api/refresh-insights", methods=["POST"])
@login_required
def refresh_insights():
    """Busca métricas de engajamento atualizadas do Instagram para posts da última semana."""
    import os as _os
    from pathlib import Path as _Path

    SESSION_DIR = _Path(_os.path.dirname(_os.path.dirname(__file__))) / "sessions"
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
                    # Insights (business accounts only — silently skip if unavailable)
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
