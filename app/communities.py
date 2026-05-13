"""
Communities — detecção de nicho por IA e recomendação de comunidades.
Fase 2: score multidimensional, filtros, dead/spam, cache otimizado.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import redis

from .ai_service import _chat, is_available

logger = logging.getLogger(__name__)

_redis = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
_CACHE_TTL      = 3600   # 1h — recomendações personalizadas
_CACHE_TTL_META = 86400  # 24h — listas de nichos/cidades (mudam raramente)
_DEAD_DAYS      = 180    # comunidade sem atividade há 180+ dias = morta


# ---------------------------------------------------------------------------
# Detecção de nicho (Fase 1 — mantida)
# ---------------------------------------------------------------------------

def detect_niche(client) -> dict:
    """Detecta nicho via posts existentes do usuário."""
    from .models import PostQueue

    captions = (
        PostQueue.query
        .filter_by(client_id=client.id)
        .order_by(PostQueue.id.desc())
        .limit(20)
        .with_entities(PostQueue.caption, PostQueue.hashtags)
        .all()
    )

    texts = []
    for c, h in captions:
        if c:
            texts.append(c[:200])
        if h:
            texts.append(h[:100])

    if not texts or not is_available():
        return {"niche": "geral", "keywords": [], "confidence": 0.0}

    sample = "\n".join(texts[:15])
    result = _chat(
        system=(
            "Você é especialista em marketing digital. "
            "Analise os textos e responda APENAS JSON válido, sem markdown."
        ),
        user=(
            f"Textos de posts do usuário:\n{sample}\n\n"
            "Detecte o nicho principal e palavras-chave relevantes.\n"
            'Responda: {"niche": "...", "keywords": ["...", "..."], "confidence": 0.0}'
        ),
        max_tokens=200,
    )

    if not result:
        return {"niche": "geral", "keywords": [], "confidence": 0.0}

    try:
        # _chat() já retorna dict parseado
        return {
            "niche": str(result.get("niche", "geral"))[:100],
            "keywords": [str(k)[:50] for k in result.get("keywords", [])[:10]],
            "confidence": float(result.get("confidence", 0.5)),
        }
    except Exception:
        logger.warning("Falha ao parsear resposta de nicho da IA")
        return {"niche": "geral", "keywords": [], "confidence": 0.0}


def save_user_niche(client_id: int, niche: str, keywords: list, confidence: float) -> None:
    from .models import db, UserNiche

    record = UserNiche.query.get(client_id)
    if record is None:
        record = UserNiche(user_id=client_id)
        db.session.add(record)

    record.niche = niche
    record.keywords = json.dumps(keywords)
    record.confidence = confidence
    record.detected_at = datetime.now(timezone.utc)
    db.session.commit()
    invalidate_user_cache(client_id)


# ---------------------------------------------------------------------------
# Score (Fase 2)
# ---------------------------------------------------------------------------

def _score(community, user_keywords: list, user_niche: str, user_city: str = "") -> int:
    """
    Score composto (0-100+):
      30 — nicho exato
      15 — cidade do usuário
      10 — verificada pelo admin
      20 — engajamento (engagement_score normalizado)
      10 por keyword encontrada no texto (max 30)
      10 — tamanho >10k membros / 5 — tamanho >1k
    """
    if community.is_spam or community.is_dead:
        return -1

    # auto-marcar morta por inatividade
    if community.last_activity_at:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_DEAD_DAYS)
        if community.last_activity_at.replace(tzinfo=timezone.utc) < cutoff:
            return -1

    score = 0
    text = " ".join(filter(None, [
        community.name,
        community.description,
        community.niche,
        community.category,
        " ".join(community.tags_list()),
    ])).lower()

    if user_niche and community.niche and community.niche.lower() == user_niche.lower():
        score += 30
    elif user_niche and community.category and user_niche.lower() in community.category.lower():
        score += 10

    if user_city and community.city and user_city.lower() in community.city.lower():
        score += 15

    if community.verified:
        score += 10

    if community.engagement_score:
        score += min(int(community.engagement_score * 0.20), 20)

    kw_points = 0
    for kw in user_keywords:
        if kw and kw.lower() in text:
            kw_points += 10
    score += min(kw_points, 30)

    mc = community.member_count or 0
    if mc > 10_000:
        score += 10
    elif mc > 1_000:
        score += 5

    return score


# ---------------------------------------------------------------------------
# Recomendações com filtros e cache otimizado
# ---------------------------------------------------------------------------

def get_recommendations(
    client_id: int,
    limit: int = 20,
    niche: str = "",
    city: str = "",
    platform: str = "",
    category: str = "",
) -> list:
    filters_key = hashlib.md5(
        f"{niche}|{city}|{platform}|{category}".encode()
    ).hexdigest()[:8]
    cache_key = f"communities:recs:{client_id}:{filters_key}"

    cached = _redis.get(cache_key)
    if cached:
        return json.loads(cached)[:limit]

    from .models import Community, UserNiche

    un = UserNiche.query.get(client_id)
    user_niche    = niche    or (un.niche if un else "")
    user_city     = city     or ""
    user_keywords = un.keywords_list() if un else []

    q = Community.query.filter_by(is_active=True, is_spam=False, is_dead=False)
    if niche:
        q = q.filter(Community.niche == niche)
    if city:
        q = q.filter(Community.city.ilike(f"%{city}%"))
    if platform:
        q = q.filter(Community.platform == platform)
    if category:
        q = q.filter(Community.category == category)

    communities = q.limit(500).all()

    scored = []
    for c in communities:
        s = _score(c, user_keywords, user_niche, user_city)
        if s >= 0:
            d = c.to_dict()
            d["score"] = s
            scored.append(d)

    scored.sort(key=lambda x: x["score"], reverse=True)

    _redis.setex(cache_key, _CACHE_TTL, json.dumps(scored[:50]))
    return scored[:limit]


# ---------------------------------------------------------------------------
# Listas de nichos e cidades (cached 24h)
# ---------------------------------------------------------------------------

def get_niches() -> list:
    cached = _redis.get("communities:niches")
    if cached:
        return json.loads(cached)

    from .models import Community, db
    from sqlalchemy import func

    rows = (
        db.session.query(Community.niche, func.count(Community.id).label("total"))
        .filter(Community.is_active == True, Community.niche.isnot(None))
        .group_by(Community.niche)
        .order_by(func.count(Community.id).desc())
        .all()
    )
    result = [{"niche": r.niche, "total": r.total} for r in rows]
    _redis.setex("communities:niches", _CACHE_TTL_META, json.dumps(result))
    return result


def get_cities() -> list:
    cached = _redis.get("communities:cities")
    if cached:
        return json.loads(cached)

    from .models import Community, db
    from sqlalchemy import func

    rows = (
        db.session.query(Community.city, func.count(Community.id).label("total"))
        .filter(Community.is_active == True, Community.city.isnot(None), Community.city != "")
        .group_by(Community.city)
        .order_by(func.count(Community.id).desc())
        .all()
    )
    result = [{"city": r.city, "total": r.total} for r in rows]
    _redis.setex("communities:cities", _CACHE_TTL_META, json.dumps(result))
    return result


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def invalidate_user_cache(client_id: int) -> None:
    for key in _redis.scan_iter(f"communities:recs:{client_id}:*"):
        _redis.delete(key)


def invalidate_meta_cache() -> None:
    _redis.delete("communities:niches")
    _redis.delete("communities:cities")
