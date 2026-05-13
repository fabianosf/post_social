"""
Communities blueprint — descoberta inteligente de comunidades (Fase 3).
"""

import json
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from .communities import (
    detect_niche,
    get_cities,
    get_niches,
    get_recommendations,
    invalidate_meta_cache,
    invalidate_user_cache,
    save_user_niche,
)
from .community_ai import (
    adapt_caption,
    detect_rules,
    growth_tips,
    invalidate_community_ai_cache,
    suggest_content,
)

communities_bp = Blueprint("communities", __name__, url_prefix="/api/communities")


@communities_bp.post("/detect-niche")
@login_required
def api_detect_niche():
    data = detect_niche(current_user)
    save_user_niche(current_user.id, data["niche"], data["keywords"], data["confidence"])
    return jsonify(data)


@communities_bp.post("/keywords")
@login_required
def api_save_keywords():
    body = request.get_json(silent=True) or {}
    keywords = [str(k)[:50] for k in body.get("keywords", [])[:20]]

    from .models import db, UserNiche
    from datetime import datetime, timezone

    record = UserNiche.query.get(current_user.id)
    if record is None:
        record = UserNiche(user_id=current_user.id, niche="geral")
        db.session.add(record)

    record.keywords = json.dumps(keywords)
    if not record.detected_at:
        record.detected_at = datetime.now(timezone.utc)
    db.session.commit()
    invalidate_user_cache(current_user.id)
    return jsonify({"ok": True, "keywords": keywords})


@communities_bp.get("/recommendations")
@login_required
def api_recommendations():
    limit    = min(int(request.args.get("limit", 20)), 50)
    niche    = request.args.get("niche", "").strip()
    city     = request.args.get("city", "").strip()
    platform = request.args.get("platform", "").strip()
    category = request.args.get("category", "").strip()

    recs = get_recommendations(
        current_user.id,
        limit=limit,
        niche=niche,
        city=city,
        platform=platform,
        category=category,
    )
    return jsonify(recs)


@communities_bp.get("/niches")
@login_required
def api_niches():
    return jsonify(get_niches())


@communities_bp.get("/cities")
@login_required
def api_cities():
    return jsonify(get_cities())


@communities_bp.post("/<int:community_id>/flag")
@login_required
def api_flag(community_id: int):
    """Admin-only: marca comunidade como spam ou morta."""
    if not current_user.is_admin:
        return jsonify({"error": "forbidden"}), 403

    body = request.get_json(silent=True) or {}
    flag = body.get("flag")  # "spam" | "dead" | "clear"
    if flag not in ("spam", "dead", "clear"):
        return jsonify({"error": "flag deve ser spam, dead ou clear"}), 400

    from .models import Community, db

    c = Community.query.get_or_404(community_id)
    c.is_spam = flag == "spam"
    c.is_dead = flag == "dead"
    if flag == "clear":
        c.is_spam = False
        c.is_dead = False
    db.session.commit()
    invalidate_meta_cache()
    return jsonify({"ok": True, "id": c.id, "flag": flag})


@communities_bp.post("/seed")
@login_required
def api_seed():
    """Admin-only: adiciona comunidade ao banco."""
    if not current_user.is_admin:
        return jsonify({"error": "forbidden"}), 403

    body = request.get_json(silent=True) or {}
    if not all(body.get(f) for f in ("platform", "name", "url")):
        return jsonify({"error": "platform, name e url são obrigatórios"}), 400

    from .models import Community, db
    from datetime import datetime, timezone

    last_activity = None
    if body.get("last_activity_at"):
        try:
            last_activity = datetime.fromisoformat(body["last_activity_at"])
        except ValueError:
            pass

    c = Community(
        platform        = body["platform"][:20],
        name            = body["name"][:200],
        description     = body.get("description"),
        url             = body["url"][:500],
        niche           = body.get("niche", "geral")[:100],
        category        = body.get("category", "")[:100],
        city            = body.get("city", "")[:100],
        member_count    = int(body.get("member_count", 0)),
        engagement_score= float(body.get("engagement_score", 0.0)),
        verified        = bool(body.get("verified", False)),
        tags            = json.dumps([str(t)[:50] for t in body.get("tags", [])[:20]]),
        last_activity_at= last_activity,
    )
    db.session.add(c)
    db.session.commit()
    invalidate_meta_cache()
    return jsonify({"ok": True, "id": c.id}), 201


@communities_bp.patch("/<int:community_id>")
@login_required
def api_update(community_id: int):
    """Admin-only: atualiza campos de uma comunidade."""
    if not current_user.is_admin:
        return jsonify({"error": "forbidden"}), 403

    from .models import Community, db

    c = Community.query.get_or_404(community_id)
    body = request.get_json(silent=True) or {}

    allowed = ("name", "description", "niche", "category", "city", "member_count",
               "engagement_score", "verified", "is_active", "tags")
    for field in allowed:
        if field in body:
            val = body[field]
            if field == "tags":
                val = json.dumps([str(t)[:50] for t in val[:20]])
            setattr(c, field, val)

    db.session.commit()
    invalidate_meta_cache()
    invalidate_community_ai_cache(community_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Fase 3 — IA contextual
# ---------------------------------------------------------------------------

@communities_bp.get("/<int:community_id>/rules")
@login_required
def api_rules(community_id: int):
    """Detecta/retorna regras e tom inferidos por IA."""
    return jsonify(detect_rules(community_id))


@communities_bp.get("/<int:community_id>/suggest-content")
@login_required
def api_suggest_content(community_id: int):
    """Sugere formatos e hooks de conteúdo ideais para esta comunidade."""
    return jsonify(suggest_content(community_id))


@communities_bp.post("/<int:community_id>/adapt-caption")
@login_required
def api_adapt_caption(community_id: int):
    """Adapta uma legenda ao contexto e tom da comunidade."""
    body = request.get_json(silent=True) or {}
    caption = str(body.get("caption", "")).strip()
    if not caption:
        return jsonify({"error": "caption é obrigatório"}), 400
    if len(caption) > 2000:
        return jsonify({"error": "caption muito longa (max 2000 chars)"}), 400
    return jsonify(adapt_caption(community_id, caption))


@communities_bp.get("/<int:community_id>/growth-tips")
@login_required
def api_growth_tips(community_id: int):
    """Dicas de growth éticas para distribuição nesta comunidade."""
    from .models import UserNiche
    un = UserNiche.query.get(current_user.id)
    user_niche = request.args.get("niche", un.niche if un else "")
    return jsonify(growth_tips(community_id, user_niche))
