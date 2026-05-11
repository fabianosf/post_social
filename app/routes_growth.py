"""
Postay — Growth Routes (Fase 9)
Dashboard executivo de crescimento e endpoints de growth analytics.
"""

import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, make_response, render_template
from flask_login import current_user, login_required

from . import ai_service
from . import growth as _growth
from .models import AIInsight, PostQueue, db

growth_bp = Blueprint("growth", __name__)

_6H  = timedelta(hours=6)
_24H = timedelta(hours=24)


# ── Helpers ───────────────────────────────────────────────────────

def _posts_last_n(days: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return PostQueue.query.filter(
        PostQueue.client_id == current_user.id,
        PostQueue.status == "posted",
        PostQueue.posted_at >= cutoff,
    ).all()


def _get_cache(insight_type: str):
    now = datetime.now(timezone.utc)
    row = (
        AIInsight.query
        .filter(
            AIInsight.client_id == current_user.id,
            AIInsight.insight_type == insight_type,
            AIInsight.post_id == None,
            (AIInsight.expires_at == None) | (AIInsight.expires_at > now),
        )
        .order_by(AIInsight.created_at.desc())
        .first()
    )
    return json.loads(row.content) if row else None


def _set_cache(insight_type: str, data: dict, ttl: timedelta = _6H):
    row = AIInsight(
        client_id=current_user.id,
        insight_type=insight_type,
        content=json.dumps(data, ensure_ascii=False),
        expires_at=datetime.now(timezone.utc) + ttl,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


# ── Página principal ──────────────────────────────────────────────

@growth_bp.route("/growth")
@login_required
def index():
    return render_template("growth.html", ai_available=ai_service.is_available())


# ── API: Resumo executivo (6h cache) ─────────────────────────────

@growth_bp.route("/api/growth/summary")
@login_required
def api_summary():
    cached = _get_cache("growth_summary")
    if cached:
        resp = make_response(jsonify({**cached, "cached": True}))
        resp.headers["Cache-Control"] = "private, max-age=300"
        return resp

    posts_30 = _posts_last_n(30)
    posts_60 = _posts_last_n(60)
    posts_prev = [p for p in posts_60 if p not in posts_30]

    data = _growth.executive_summary(posts_30, posts_prev)
    _set_cache("growth_summary", data, _6H)
    resp = make_response(jsonify(data))
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


# ── API: Insights IA (24h cache) ─────────────────────────────────

@growth_bp.route("/api/growth/insights")
@login_required
def api_insights():
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503

    cached = _get_cache("growth_insights")
    if cached:
        return jsonify({**cached, "cached": True})

    posts_30 = _posts_last_n(30)
    posts_60 = _posts_last_n(60)
    posts_prev = [p for p in posts_60 if p not in posts_30]

    summary = _growth.executive_summary(posts_30, posts_prev)
    result  = ai_service.generate_growth_insights(summary)
    if result is None:
        return jsonify({"error": "Falha ao gerar insights. Tente novamente."}), 500

    _set_cache("growth_insights", result, _24H)
    return jsonify(result)


# ── API: Benchmark (24h cache) ────────────────────────────────────

@growth_bp.route("/api/growth/benchmark")
@login_required
def api_benchmark():
    cached = _get_cache("growth_benchmark")
    if cached:
        return jsonify({**cached, "cached": True})

    posts_30 = _posts_last_n(30)
    data = _growth.benchmark_data(posts_30)
    _set_cache("growth_benchmark", data, _24H)
    return jsonify(data)
