"""
Growth Intelligence blueprint — benchmarking e oportunidades de crescimento (Fase 4).
Prefixo: /api/growth-intel  (não conflita com /api/growth existente)
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from .growth_engine import (
    competitive_score,
    get_competitive_analysis,
    get_growth_opportunities,
    get_niche_trends,
    invalidate_growth_cache,
)

growth_intel_bp = Blueprint("growth_intel", __name__, url_prefix="/api/growth-intel")


def _pro_json():
    if current_user.has_pro_features():
        return None
    return jsonify({"error": "Recurso Pro ou Agency"}), 403


# ---------------------------------------------------------------------------
# Concorrentes
# ---------------------------------------------------------------------------

@growth_intel_bp.get("/competitors")
@login_required
def api_list_competitors():
    from .models import Competitor
    comps = Competitor.query.filter_by(client_id=current_user.id).order_by(Competitor.id.desc()).all()
    return jsonify([c.to_dict() for c in comps])


@growth_intel_bp.post("/competitors")
@login_required
def api_add_competitor():
    denied = _pro_json()
    if denied:
        return denied
    from .models import Competitor, db
    n = Competitor.query.filter_by(client_id=current_user.id).count()
    if n >= current_user.max_competitors():
        return jsonify({"error": f"Limite de {current_user.max_competitors()} concorrentes no seu plano"}), 403
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"error": "name é obrigatório"}), 400

    c = Competitor(
        client_id   = current_user.id,
        name        = name[:200],
        niche       = str(body.get("niche", ""))[:100] or None,
        ig_username = str(body.get("ig_username", ""))[:100].lstrip("@") or None,
        website_url = str(body.get("website_url", ""))[:500] or None,
        notes       = str(body.get("notes", ""))[:1000] or None,
    )
    db.session.add(c)
    db.session.commit()
    invalidate_growth_cache(current_user.id)
    return jsonify({"ok": True, "id": c.id}), 201


@growth_intel_bp.delete("/competitors/<int:competitor_id>")
@login_required
def api_delete_competitor(competitor_id: int):
    from .models import Competitor, db
    c = Competitor.query.filter_by(id=competitor_id, client_id=current_user.id).first_or_404()
    db.session.delete(c)
    db.session.commit()
    invalidate_growth_cache(current_user.id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Tendências por nicho
# ---------------------------------------------------------------------------

@growth_intel_bp.get("/trends")
@login_required
def api_trends():
    denied = _pro_json()
    if denied:
        return denied
    from .models import UserNiche
    un = UserNiche.query.get(current_user.id)
    niche = request.args.get("niche", un.niche if un else "geral")
    return jsonify(get_niche_trends(niche))


# ---------------------------------------------------------------------------
# Score competitivo
# ---------------------------------------------------------------------------

@growth_intel_bp.get("/competitive-score")
@login_required
def api_competitive_score():
    denied = _pro_json()
    if denied:
        return denied
    from .models import UserNiche
    un = UserNiche.query.get(current_user.id)
    niche = request.args.get("niche", un.niche if un else "geral")
    city  = request.args.get("city", "")
    return jsonify(competitive_score(niche, city))


# ---------------------------------------------------------------------------
# Oportunidades de crescimento
# ---------------------------------------------------------------------------

@growth_intel_bp.get("/opportunities")
@login_required
def api_opportunities():
    return jsonify(get_growth_opportunities(current_user.id))


# ---------------------------------------------------------------------------
# Análise competitiva via IA
# ---------------------------------------------------------------------------

@growth_intel_bp.get("/analysis")
@login_required
def api_analysis():
    denied = _pro_json()
    if denied:
        return denied
    return jsonify(get_competitive_analysis(current_user.id))
