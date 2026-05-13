"""
Growth Engine — benchmarking, tendências e oportunidades de crescimento (Fase 4).
Sem scraping. Dados: comunidades internas + concorrentes inseridos manualmente + IA.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import redis

from .ai_service import _chat, is_available

logger = logging.getLogger(__name__)

_redis = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)

_TTL_TRENDS      = 86400   # 24h — tendências de nicho
_TTL_OPPS        = 21600   # 6h  — oportunidades de crescimento
_TTL_COMPETITIVE = 21600   # 6h  — análise competitiva
_TREND_DB_DAYS   = 7       # regenara NicheTrend no DB após 7 dias


# ---------------------------------------------------------------------------
# 1. Tendências por nicho (AI + cache duplo: Redis + NicheTrend table)
# ---------------------------------------------------------------------------

def get_niche_trends(niche: str) -> dict:
    """
    Tendências, conteúdos e oportunidades para um nicho.
    Cache Redis 24h; fallback no DB (NicheTrend).
    """
    cache_key = f"growth_intel:trends:{niche}"
    cached = _redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # Tenta DB antes de chamar IA
    from .models import NicheTrend
    db_record = NicheTrend.query.get(niche)
    cutoff = datetime.now(timezone.utc) - timedelta(days=_TREND_DB_DAYS)
    if db_record and db_record.updated_at and db_record.updated_at > cutoff:
        data = db_record.data()
        _redis.setex(cache_key, _TTL_TRENDS, json.dumps(data))
        return data

    data = _fetch_trends_from_ai(niche)
    _persist_trend(niche, data)
    _redis.setex(cache_key, _TTL_TRENDS, json.dumps(data))
    return data


def _fetch_trends_from_ai(niche: str) -> dict:
    if not is_available():
        return _trend_fallback(niche)

    result = _chat(
        system=(
            "Você é analista de tendências digitais no mercado brasileiro. "
            "Responda APENAS JSON válido, sem markdown."
        ),
        user=(
            f"Analise o nicho: {niche}\n\n"
            "Identifique tendências atuais, oportunidades de crescimento e "
            "tipos de conteúdo em alta para criadores neste nicho no Brasil.\n"
            'Responda: {"trends": ["tendência 1", "tendência 2"], '
            '"rising_topics": ["tópico emergente 1"], '
            '"content_opportunities": ["oportunidade 1", "oportunidade 2"], '
            '"saturation_level": "baixa|média|alta", '
            '"growth_potential": "baixo|médio|alto", '
            '"tip": "dica principal para se destacar"}'
        ),
        max_tokens=400,
    )
    return result if result else _trend_fallback(niche)


def _trend_fallback(niche: str) -> dict:
    return {
        "trends": [], "rising_topics": [], "content_opportunities": [],
        "saturation_level": "média", "growth_potential": "médio", "tip": "",
    }


def _persist_trend(niche: str, data: dict) -> None:
    try:
        from .models import NicheTrend, db
        record = NicheTrend.query.get(niche)
        if record is None:
            record = NicheTrend(niche=niche)
            db.session.add(record)
        record.trend_data = json.dumps(data)
        record.updated_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception as e:
        logger.warning(f"Falha ao persistir NicheTrend: {e}")


# ---------------------------------------------------------------------------
# 2. Score competitivo por nicho
# ---------------------------------------------------------------------------

def competitive_score(niche: str, city: str = "") -> dict:
    """
    Avalia nível de competição e oportunidade de crescimento em um nicho/cidade.
    Baseado em dados internos (quantas comunidades existem, distribuição geográfica).
    """
    from .models import Community, db
    from sqlalchemy import func

    total_communities = (
        db.session.query(func.count(Community.id))
        .filter(Community.is_active == True, Community.niche == niche)
        .scalar() or 0
    )

    city_communities = 0
    if city:
        city_communities = (
            db.session.query(func.count(Community.id))
            .filter(
                Community.is_active == True,
                Community.niche == niche,
                Community.city.ilike(f"%{city}%"),
            )
            .scalar() or 0
        )

    # Heurística simples: <5 comunidades = oportunidade alta
    if total_communities < 5:
        opportunity = "alta"
        saturation  = "baixa"
    elif total_communities < 20:
        opportunity = "média"
        saturation  = "média"
    else:
        opportunity = "baixa"
        saturation  = "alta"

    city_opportunity = "alta" if city and city_communities < 3 else "média"

    return {
        "niche": niche,
        "city": city,
        "total_communities": total_communities,
        "city_communities": city_communities,
        "opportunity": opportunity,
        "saturation": saturation,
        "city_opportunity": city_opportunity if city else None,
    }


# ---------------------------------------------------------------------------
# 3. Growth opportunities (combina comunidades + nicho + concorrentes)
# ---------------------------------------------------------------------------

def get_growth_opportunities(client_id: int) -> dict:
    cache_key = f"growth_intel:opps:{client_id}"
    cached = _redis.get(cache_key)
    if cached:
        return json.loads(cached)

    from .models import Community, Competitor, UserNiche, db
    from sqlalchemy import func

    un = UserNiche.query.get(client_id)
    user_niche = un.niche if un else "geral"
    user_keywords = un.keywords_list() if un else []
    competitors = Competitor.query.filter_by(client_id=client_id).all()
    competitor_niches = list({c.niche for c in competitors if c.niche})

    # Comunidades sem concorrência direta: nicho do usuário mas não dos concorrentes
    underserved = (
        Community.query
        .filter(Community.is_active == True, Community.niche == user_niche)
        .order_by(Community.engagement_score.desc())
        .limit(10)
        .all()
    )

    # Nichos adjacentes com poucas comunidades
    adjacent_niches = (
        db.session.query(Community.niche, func.count(Community.id).label("total"))
        .filter(Community.is_active == True, Community.niche != user_niche)
        .group_by(Community.niche)
        .order_by(func.count(Community.id).asc())
        .limit(5)
        .all()
    )

    score = competitive_score(user_niche)

    result = {
        "user_niche": user_niche,
        "competitive_score": score,
        "underserved_communities": [c.to_dict() for c in underserved],
        "adjacent_niches": [{"niche": r.niche, "community_count": r.total} for r in adjacent_niches],
        "competitor_count": len(competitors),
        "competitor_niches": competitor_niches,
    }

    _redis.setex(cache_key, _TTL_OPPS, json.dumps(result))
    return result


# ---------------------------------------------------------------------------
# 4. Análise competitiva via IA
# ---------------------------------------------------------------------------

def get_competitive_analysis(client_id: int) -> dict:
    cache_key = f"growth_intel:analysis:{client_id}"
    cached = _redis.get(cache_key)
    if cached:
        return json.loads(cached)

    from .models import Competitor, UserNiche

    un = UserNiche.query.get(client_id)
    user_niche = un.niche if un else "geral"
    competitors = Competitor.query.filter_by(client_id=client_id).limit(10).all()

    if not is_available():
        return {"insights": [], "strategy": "", "differentiation": []}

    comp_list = "\n".join(
        f"- {c.name} (nicho: {c.niche or 'similar'}, ig: @{c.ig_username or 'N/A'})"
        for c in competitors
    ) or "Nenhum concorrente cadastrado"

    result = _chat(
        system=(
            "Você é estrategista de growth para criadores de conteúdo brasileiros. "
            "Responda APENAS JSON válido, sem markdown."
        ),
        user=(
            f"Nicho do usuário: {user_niche}\n"
            f"Concorrentes identificados:\n{comp_list}\n\n"
            "Analise o cenário competitivo e sugira onde e como crescer de forma "
            "diferenciada, identificando oportunidades que concorrentes não exploram.\n"
            'Responda: {"insights": ["insight 1", "insight 2"], '
            '"strategy": "estratégia principal recomendada", '
            '"differentiation": ["diferencial 1", "diferencial 2"], '
            '"community_types": ["tipo de comunidade ideal 1", "tipo 2"]}'
        ),
        max_tokens=400,
    )

    data = result if result else {"insights": [], "strategy": "", "differentiation": [], "community_types": []}
    _redis.setex(cache_key, _TTL_COMPETITIVE, json.dumps(data))
    return data


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def invalidate_growth_cache(client_id: int) -> None:
    for key in _redis.scan_iter(f"growth_intel:*:{client_id}*"):
        _redis.delete(key)
