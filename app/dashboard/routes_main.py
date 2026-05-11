"""
Rotas principais do dashboard: index, stats, notificações.
"""

import os
from datetime import datetime, timezone, timedelta

from flask import flash, redirect, render_template, request, url_for, session
from flask_login import login_required, current_user

from ..models import db, InstagramAccount, PostQueue, CaptionTemplate
from .helpers import SAFE_LIMITS, BRAZIL_TZ
from . import dashboard_bp


@dashboard_bp.route("/dashboard")
@dashboard_bp.route("/painel")
@login_required
def index():
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()
    status_filter = request.args.get("status", "all")

    ACTIVE_STATUSES = ["pending", "draft", "failed", "processing"]
    queue_query = PostQueue.query.filter(
        PostQueue.client_id == current_user.id,
        PostQueue.status.in_(ACTIVE_STATUSES),
    )
    if status_filter not in ("all", "posted"):
        queue_query = queue_query.filter_by(status=status_filter)
    posts = queue_query.order_by(PostQueue.created_at.desc()).limit(100).all()

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

    plan_info = {
        "plan": "pro" if current_user.is_admin else current_user.plan,
        "used": current_user.posts_this_month or 0,
        "limit": current_user.get_monthly_limit(),
    }

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
                if days_since in (81, 85, 89):
                    try:
                        from modules.telegram_notify import notify_session_expiring
                        notify_session_expiring(current_user, acc, days_since)
                    except Exception:
                        pass

    brand = {
        "name": current_user.brand_name or "Postay",
        "color": current_user.brand_color or "#7c5cff",
    }

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
            "feed_used": ig_today,
            "feed_max": MAX_DAY,
            "feed_remaining": ig_remaining,
            "blocked": ig_remaining <= 0,
        }

    tiktok_configured = bool(os.environ.get("TIKTOK_CLIENT_KEY", "").strip())
    active_account_id = session.get("active_account_id") or current_user.default_account_id

    trial_days_left = None
    if not current_user.is_admin and current_user.plan == "pro" and current_user.plan_expires_at and not current_user.mp_subscription_id:
        expires = current_user.plan_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        diff = (expires - datetime.now(timezone.utc)).days
        trial_days_left = max(0, diff)

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
        trial_days_left=trial_days_left,
    )


@dashboard_bp.route("/notifications/dismiss", methods=["POST"])
@login_required
def dismiss_notifications():
    PostQueue.query.filter_by(client_id=current_user.id, notified=False).update({"notified": True})
    db.session.commit()
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/stats")
@login_required
def stats_page():
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

    by_type = {}
    for ptype in ["photo", "album", "reels", "story"]:
        by_type[ptype] = all_posts.filter_by(post_type=ptype, status="posted").count()

    total_attempted = stats["posted"] + stats["failed"]
    success_rate = round((stats["posted"] / total_attempted * 100) if total_attempted > 0 else 0)

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

    top_post = max(week_posts, key=lambda p: (p.ig_likes or 0) + (p.ig_comments or 0), default=None)

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
