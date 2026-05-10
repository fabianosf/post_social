"""
Postay — AI Blueprint
Rotas: /ai (página principal) e /api/ai/* (AJAX)
"""

import json
from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user

from .models import db, PostQueue, AIInsight
from . import ai_service

ai_bp = Blueprint("ai", __name__)

_CACHE_TTL = timedelta(hours=24)


# ── Helpers ───────────────────────────────────────────────────────

def _get_cache(client_id: int, insight_type: str, post_id: int | None = None) -> dict | None:
    now = datetime.now(timezone.utc)
    q = AIInsight.query.filter(
        AIInsight.client_id == client_id,
        AIInsight.insight_type == insight_type,
        AIInsight.post_id == post_id,
        (AIInsight.expires_at == None) | (AIInsight.expires_at > now),
    ).order_by(AIInsight.created_at.desc()).first()
    return json.loads(q.content) if q else None


def _set_cache(client_id: int, insight_type: str, data: dict,
               post_id: int | None = None, ttl: timedelta = _CACHE_TTL):
    expires = datetime.now(timezone.utc) + ttl
    row = AIInsight(
        client_id=client_id,
        post_id=post_id,
        insight_type=insight_type,
        content=json.dumps(data, ensure_ascii=False),
        expires_at=expires,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _posted_last_n_days(days=30):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return PostQueue.query.filter(
        PostQueue.client_id == current_user.id,
        PostQueue.status == "posted",
        PostQueue.posted_at >= cutoff,
    ).all()


# ── Página principal ──────────────────────────────────────────────

@ai_bp.route("/ai")
@login_required
def index():
    return render_template(
        "ai_assistant.html",
        ai_available=ai_service.is_available(),
        ai_provider=ai_service._AI_PROVIDER,
    )


# ── API: Analisar legenda ─────────────────────────────────────────

@ai_bp.route("/api/ai/caption", methods=["POST"])
@login_required
def api_caption():
    body = request.get_json(silent=True) or {}
    caption = (body.get("caption") or "").strip()
    if not caption:
        return jsonify({"error": "Legenda obrigatória"}), 400
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503

    result = ai_service.analyze_caption(caption)
    if result is None:
        return jsonify({"error": "Falha na análise. Tente novamente."}), 500
    return jsonify(result)


# ── API: Analisar hook ────────────────────────────────────────────

@ai_bp.route("/api/ai/hook", methods=["POST"])
@login_required
def api_hook():
    body = request.get_json(silent=True) or {}
    caption = (body.get("caption") or "").strip()
    if not caption:
        return jsonify({"error": "Legenda obrigatória"}), 400
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503

    result = ai_service.analyze_hook(caption)
    if result is None:
        return jsonify({"error": "Falha na análise. Tente novamente."}), 500
    return jsonify(result)


# ── API: Sugerir hashtags ─────────────────────────────────────────

@ai_bp.route("/api/ai/hashtags", methods=["POST"])
@login_required
def api_hashtags():
    body = request.get_json(silent=True) or {}
    caption = (body.get("caption") or "").strip()
    niche = (body.get("niche") or "").strip()
    post_type = body.get("type", "photo")
    if not niche and not caption:
        return jsonify({"error": "Informe nicho ou legenda"}), 400
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503

    result = ai_service.suggest_hashtags_ai(caption, niche, post_type)
    if result is None:
        return jsonify({"error": "Falha ao gerar hashtags. Tente novamente."}), 500
    return jsonify(result)


# ── API: Sugerir CTA ──────────────────────────────────────────────

@ai_bp.route("/api/ai/cta", methods=["POST"])
@login_required
def api_cta():
    body = request.get_json(silent=True) or {}
    caption = (body.get("caption") or "").strip()
    goal = body.get("goal", "engajamento")
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503

    result = ai_service.suggest_cta_ai(caption, goal)
    if result is None:
        return jsonify({"error": "Falha ao gerar CTAs. Tente novamente."}), 500
    return jsonify(result)


# ── API: Score de viralização de um post ─────────────────────────

@ai_bp.route("/api/ai/virality/<int:post_id>", methods=["POST"])
@login_required
def api_virality(post_id: int):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first_or_404()
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503

    cached = _get_cache(current_user.id, "virality", post_id)
    if cached:
        return jsonify({**cached, "cached": True})

    metrics = {
        "likes": post.ig_likes or 0,
        "comments": post.ig_comments or 0,
        "saves": post.ig_saves or 0,
        "reach": post.ig_reach or 0,
    }
    result = ai_service.virality_score_ai(post.caption or "", metrics)
    if result is None:
        return jsonify({"error": "Falha na análise. Tente novamente."}), 500

    _set_cache(current_user.id, "virality", result, post_id, ttl=timedelta(days=7))
    return jsonify(result)


# ── API: Previsão de performance ──────────────────────────────────

@ai_bp.route("/api/ai/predict", methods=["POST"])
@login_required
def api_predict():
    body = request.get_json(silent=True) or {}
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503

    posts = _posted_last_n_days(30)
    from .analytics import post_score, type_performance, best_time_analysis
    scored = [p for p in posts if p.instagram_media_id]
    avg_score = sum(post_score(p) for p in scored) / len(scored) if scored else 0
    avg_reach = sum(p.ig_reach or 0 for p in scored) / len(scored) if scored else 0
    types = type_performance(posts)
    bt = best_time_analysis(posts)

    history = {
        "count": len(posts),
        "avg_reach": round(avg_reach),
        "avg_score": avg_score,
        "best_type": types[0]["type"] if types else "photo",
        "best_hour": bt["best_hours"][0][0] if bt.get("best_hours") else 12,
    }
    result = ai_service.predict_performance_ai(body, history)
    if result is None:
        return jsonify({"error": "Falha na previsão. Tente novamente."}), 500
    return jsonify(result)


# ── API: Insights gerais da conta (com cache 24h) ─────────────────

@ai_bp.route("/api/ai/insights")
@login_required
def api_insights():
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503

    cached = _get_cache(current_user.id, "account_insights")
    if cached:
        return jsonify({**cached, "cached": True})

    posts_30 = _posted_last_n_days(30)
    posts_60 = _posted_last_n_days(60)
    posts_prev = [p for p in posts_60 if p not in posts_30]

    from .analytics import post_score, type_performance, period_comparison
    from .recommendations import detect_patterns

    scored = [p for p in posts_30 if p.instagram_media_id]
    avg_score = round(sum(post_score(p) for p in scored) / len(scored), 2) if scored else 0
    types = type_performance(posts_30)
    comparison = period_comparison(posts_30, posts_prev)
    patterns = detect_patterns(posts_30)

    stats = {
        "count": len([p for p in posts_30 if p.status == "posted"]),
        "total_reach": comparison["current"]["reach"],
        "total_likes": comparison["current"]["likes"],
        "total_saves": comparison["current"]["saves"],
        "avg_score": avg_score,
        "reach_growth": comparison["delta"].get("reach", 0),
        "best_type": types[0]["label"] if types else "desconhecido",
        "consistency": patterns.get("consistency", "desconhecida"),
    }

    result = ai_service.generate_ai_insights(stats)
    if result is None:
        return jsonify({"error": "Falha ao gerar insights. Tente novamente."}), 500

    _set_cache(current_user.id, "account_insights", result)
    return jsonify(result)


# ── API: Limpar cache de IA ───────────────────────────────────────

@ai_bp.route("/api/ai/cache/clear", methods=["POST"])
@login_required
def api_clear_cache():
    AIInsight.query.filter_by(client_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════
# FASE 7 — ENDPOINTS DE GERAÇÃO DE CONTEÚDO
# ═══════════════════════════════════════════════════════════════════

def _gen_guard():
    """Retorna 503 se IA não configurada, None se OK."""
    if not ai_service.is_available():
        return jsonify({"error": "IA não configurada"}), 503
    return None


# ── Gerar legenda ─────────────────────────────────────────────────

@ai_bp.route("/api/ai/generate/caption", methods=["POST"])
@login_required
def gen_caption():
    err = _gen_guard()
    if err:
        return err
    b = request.get_json(silent=True) or {}
    niche = b.get("niche", "geral")
    topic = (b.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Informe o tema/tópico do post"}), 400
    result = ai_service.generate_caption(
        niche=niche,
        topic=topic,
        post_type=b.get("post_type", "photo"),
        tone=b.get("tone", "informativo"),
        goal=b.get("goal", "engajamento"),
        length=b.get("length", "media"),
    )
    return jsonify(result) if result else (jsonify({"error": "Falha na geração"}), 500)


# ── Gerar hooks ───────────────────────────────────────────────────

@ai_bp.route("/api/ai/generate/hooks", methods=["POST"])
@login_required
def gen_hooks():
    err = _gen_guard()
    if err:
        return err
    b = request.get_json(silent=True) or {}
    topic = (b.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Informe o tema"}), 400
    result = ai_service.generate_hooks(
        niche=b.get("niche", "geral"),
        topic=topic,
        quantity=min(int(b.get("quantity", 5)), 8),
    )
    return jsonify(result) if result else (jsonify({"error": "Falha na geração"}), 500)


# ── Gerar títulos ─────────────────────────────────────────────────

@ai_bp.route("/api/ai/generate/titles", methods=["POST"])
@login_required
def gen_titles():
    err = _gen_guard()
    if err:
        return err
    b = request.get_json(silent=True) or {}
    topic = (b.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "Informe o tema"}), 400
    result = ai_service.generate_titles(
        niche=b.get("niche", "geral"),
        topic=topic,
        post_type=b.get("post_type", "reels"),
    )
    return jsonify(result) if result else (jsonify({"error": "Falha na geração"}), 500)


# ── Reescrever legenda ────────────────────────────────────────────

@ai_bp.route("/api/ai/generate/rewrite", methods=["POST"])
@login_required
def gen_rewrite():
    err = _gen_guard()
    if err:
        return err
    b = request.get_json(silent=True) or {}
    original = (b.get("caption") or "").strip()
    if not original:
        return jsonify({"error": "Cole a legenda original"}), 400
    result = ai_service.rewrite_caption(
        original=original,
        goal=b.get("goal", "engajamento"),
        tone=b.get("tone", "informativo"),
    )
    return jsonify(result) if result else (jsonify({"error": "Falha na reescrita"}), 500)


# ── Otimizar retenção ─────────────────────────────────────────────

@ai_bp.route("/api/ai/generate/retention", methods=["POST"])
@login_required
def gen_retention():
    err = _gen_guard()
    if err:
        return err
    b = request.get_json(silent=True) or {}
    caption = (b.get("caption") or "").strip()
    if not caption:
        return jsonify({"error": "Cole a legenda para otimizar"}), 400
    result = ai_service.optimize_retention(caption)
    return jsonify(result) if result else (jsonify({"error": "Falha na otimização"}), 500)


# ── Sugestões de viralização ──────────────────────────────────────

@ai_bp.route("/api/ai/generate/viralize", methods=["POST"])
@login_required
def gen_viralize():
    err = _gen_guard()
    if err:
        return err
    b = request.get_json(silent=True) or {}
    caption = (b.get("caption") or "").strip()
    if not caption:
        return jsonify({"error": "Cole o conteúdo para analisar"}), 400
    result = ai_service.suggest_viralization(caption, b.get("niche", "geral"))
    return jsonify(result) if result else (jsonify({"error": "Falha na análise"}), 500)


# ── Gerar calendário de conteúdo ──────────────────────────────────

@ai_bp.route("/api/ai/generate/calendar", methods=["POST"])
@login_required
def gen_calendar():
    err = _gen_guard()
    if err:
        return err
    b = request.get_json(silent=True) or {}
    niche = b.get("niche", "geral")
    posts_per_week = max(1, min(7, int(b.get("posts_per_week", 3))))
    weeks = max(1, min(4, int(b.get("weeks", 2))))
    goals = b.get("goals", [])

    result = ai_service.generate_content_calendar(
        niche=niche,
        posts_per_week=posts_per_week,
        weeks=weeks,
        goals=goals if isinstance(goals, list) else [goals],
    )
    return jsonify(result) if result else (jsonify({"error": "Falha na geração do calendário"}), 500)


# ── Metadados: lista de nichos disponíveis ────────────────────────

@ai_bp.route("/api/ai/niches")
@login_required
def api_niches():
    return jsonify(ai_service.NICHES_LIST)
