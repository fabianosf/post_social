"""
Postay Analytics — rotas de analytics inteligentes.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request, jsonify, session
from flask_login import login_required, current_user

from .models import db, PostQueue, InstagramAccount
from .analytics import (
    rank_posts, best_time_analysis, period_comparison,
    type_performance, generate_insights, growth_trend,
    post_score, score_label, score_color,
    _DAY_NAMES, _BLOCK_LABELS,
)

analytics_bp = Blueprint("analytics", __name__)
BRT = ZoneInfo("America/Sao_Paulo")


def _period_posts(client_id: int, days: int, offset_days: int = 0):
    """Busca posts publicados em uma janela de 'days' dias com offset opcional."""
    end = datetime.now(timezone.utc) - timedelta(days=offset_days)
    start = end - timedelta(days=days)
    return PostQueue.query.filter(
        PostQueue.client_id == client_id,
        PostQueue.posted_at >= start,
        PostQueue.posted_at <= end,
    ).all()


def _daily_series(client_id: int, days: int) -> list[dict]:
    """Série diária de métricas para gráfico de tendência."""
    now = datetime.now(timezone.utc)
    series = []
    for i in range(days - 1, -1, -1):
        day_end = now - timedelta(days=i)
        day_start = day_end - timedelta(days=1)
        posts = PostQueue.query.filter(
            PostQueue.client_id == client_id,
            PostQueue.status == "posted",
            PostQueue.posted_at >= day_start,
            PostQueue.posted_at <= day_end,
        ).all()
        series.append({
            "day": (now - timedelta(days=i)).astimezone(BRT).strftime("%d/%m"),
            "count": len(posts),
            "likes": sum(p.ig_likes or 0 for p in posts),
            "comments": sum(p.ig_comments or 0 for p in posts),
            "saves": sum(p.ig_saves or 0 for p in posts),
            "reach": sum(p.ig_reach or 0 for p in posts),
        })
    return series


@analytics_bp.route("/analytics")
@login_required
def index():
    days = request.args.get("days", 30, type=int)
    days = days if days in (7, 30, 90) else 30

    # Posts do período atual e anterior (para comparação)
    posts_current = _period_posts(current_user.id, days)
    posts_previous = _period_posts(current_user.id, days, offset_days=days)

    # Posts com dados de engajamento (para score e best time)
    posts_with_metrics = [p for p in posts_current if p.instagram_media_id]

    # Computar analytics
    ranked = rank_posts(posts_with_metrics)[:20]      # top 20 para tabela
    best_time = best_time_analysis(posts_with_metrics)
    comparison = period_comparison(posts_current, posts_previous)
    types = type_performance(posts_with_metrics)
    insights = generate_insights(posts_with_metrics, best_time, comparison, types)
    daily = _daily_series(current_user.id, min(days, 30))
    trend = growth_trend(daily)

    # Heatmap serializado para Jinja2 (não passa dict com tuple keys)
    heatmap_list = [
        {"wd": wd, "block": blk, "intensity": val}
        for (wd, blk), val in best_time["heatmap"].items()
    ]

    # Score médio geral do período
    all_scores = [item["score"] for item in ranked]
    avg_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0

    brand = {
        "name": current_user.brand_name or "Postay",
        "color": current_user.brand_color or "#7c5cff",
    }

    return render_template(
        "analytics.html",
        days=days,
        ranked=ranked,
        best_time=best_time,
        comparison=comparison,
        types=types,
        insights=insights,
        daily=daily,
        trend=trend,
        heatmap_list=heatmap_list,
        avg_score=avg_score,
        avg_score_label=score_label(avg_score),
        avg_score_color=score_color(avg_score),
        day_names=_DAY_NAMES,
        block_labels=_BLOCK_LABELS,
        brand=brand,
        total_posts_analyzed=best_time["total_posts_analyzed"],
    )


# ── API JSON ──────────────────────────────────────────────────────

@analytics_bp.route("/api/analytics/score/<int:post_id>")
@login_required
def api_post_score(post_id):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if not post:
        return jsonify({"error": "not found"}), 404
    s = post_score(post)
    return jsonify({
        "post_id": post_id,
        "score": s,
        "label": score_label(s),
        "color": score_color(s),
    })


@analytics_bp.route("/api/analytics/summary")
@login_required
def api_summary():
    """Resumo rápido para widgets no dashboard principal."""
    days = 7
    posts = _period_posts(current_user.id, days)
    posts_prev = _period_posts(current_user.id, days, offset_days=days)
    comparison = period_comparison(posts, posts_prev)
    best = best_time_analysis([p for p in posts if p.instagram_media_id])

    best_hour = best["best_hours"][0][0] if best["best_hours"] else None
    return jsonify({
        "reach_delta": comparison["delta"].get("reach", 0),
        "count_delta": comparison["delta"].get("count", 0),
        "best_hour": best_hour,
        "current_count": comparison["current"]["count"],
    })
