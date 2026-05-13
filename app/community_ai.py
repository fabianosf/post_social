"""
Community AI — IA contextual por comunidade (Fase 3).
Reutiliza _chat() do ai_service.py. Tudo cacheado no Redis.
"""

import hashlib
import json
import logging
import os

import redis

from .ai_service import _chat, is_available

logger = logging.getLogger(__name__)

_redis = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)

_TTL_RULES   = 86400   # 24h — regras mudam pouco
_TTL_CONTENT = 21600   # 6h  — sugestões de conteúdo
_TTL_GROWTH  = 21600   # 6h  — dicas de growth
_TTL_ADAPT   = 3600    # 1h  — adaptação de legenda (depende do input)


# ---------------------------------------------------------------------------
# Contexto da comunidade (usado em todos os prompts)
# ---------------------------------------------------------------------------

def _ctx(community) -> str:
    parts = [f"Comunidade: {community.name}"]
    if community.platform:
        parts.append(f"Plataforma: {community.platform}")
    if community.niche:
        parts.append(f"Nicho: {community.niche}")
    if community.category:
        parts.append(f"Categoria: {community.category}")
    if community.city:
        parts.append(f"Cidade/região: {community.city}")
    if community.tone:
        parts.append(f"Tom esperado: {community.tone}")
    if community.member_count:
        parts.append(f"Membros: {community.member_count:,}")
    rules = community.rules_list()
    if rules:
        parts.append(f"Regras: {', '.join(rules)}")
    if community.description:
        parts.append(f"Descrição: {community.description[:300]}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 1. Detectar regras da comunidade via IA
# ---------------------------------------------------------------------------

def detect_rules(community_id: int) -> dict:
    """
    Infere regras e tom da comunidade a partir da descrição.
    Retorna {"rules": [...], "tone": "...", "topics": [...]}.
    """
    cache_key = f"community_ai:rules:{community_id}"
    cached = _redis.get(cache_key)
    if cached:
        return json.loads(cached)

    from .models import Community
    c = Community.query.get(community_id)
    if not c or not is_available():
        return _rules_fallback(c)

    result = _chat(
        system=(
            "Você é especialista em comunidades digitais brasileiras. "
            "Responda APENAS JSON válido, sem markdown."
        ),
        user=(
            f"Analise esta comunidade:\n{_ctx(c)}\n\n"
            "Infira: regras implícitas, tom predominante, tópicos bem-vindos e proibidos.\n"
            'Responda: {"rules": ["regra 1", "regra 2"], '
            '"tone": "casual|formal|educativo|humoristico", '
            '"welcome_topics": ["tópico 1"], '
            '"forbidden_topics": ["tópico proibido"]}'
        ),
        max_tokens=300,
    )

    data = result if result else _rules_fallback(c)
    _redis.setex(cache_key, _TTL_RULES, json.dumps(data))
    return data


def _rules_fallback(community) -> dict:
    tone = community.tone if community else "casual"
    return {"rules": [], "tone": tone, "welcome_topics": [], "forbidden_topics": []}


# ---------------------------------------------------------------------------
# 2. Sugerir conteúdo ideal para a comunidade
# ---------------------------------------------------------------------------

def suggest_content(community_id: int) -> dict:
    """
    Retorna tipos e formatos de conteúdo que melhor performam nesta comunidade.
    Resultado: {"formats": [...], "hooks": [...], "best_times": [...], "tips": [...]}.
    """
    cache_key = f"community_ai:content:{community_id}"
    cached = _redis.get(cache_key)
    if cached:
        return json.loads(cached)

    from .models import Community
    c = Community.query.get(community_id)
    if not c or not is_available():
        return {"formats": [], "hooks": [], "best_times": [], "tips": []}

    result = _chat(
        system=(
            "Você é estrategista de conteúdo para redes sociais brasileiras. "
            "Responda APENAS JSON válido, sem markdown."
        ),
        user=(
            f"Dados da comunidade:\n{_ctx(c)}\n\n"
            "Sugira o melhor tipo de conteúdo para engajar esta audiência.\n"
            'Responda: {"formats": ["post carrossel", "vídeo curto"], '
            '"hooks": ["frase de abertura 1", "frase 2"], '
            '"best_times": ["19h", "12h"], '
            '"tips": ["dica prática 1", "dica 2", "dica 3"]}'
        ),
        max_tokens=400,
    )

    data = result if result else {"formats": [], "hooks": [], "best_times": [], "tips": []}
    _redis.setex(cache_key, _TTL_CONTENT, json.dumps(data))
    return data


# ---------------------------------------------------------------------------
# 3. Adaptar legenda para a comunidade
# ---------------------------------------------------------------------------

def adapt_caption(community_id: int, caption: str) -> dict:
    """
    Reescreve uma legenda adaptando tom, contexto e regras da comunidade.
    Retorna {"adapted": str, "changes": [...], "warnings": [...]}.
    """
    caption_hash = hashlib.md5(caption[:500].encode()).hexdigest()[:8]
    cache_key = f"community_ai:adapt:{community_id}:{caption_hash}"
    cached = _redis.get(cache_key)
    if cached:
        return json.loads(cached)

    from .models import Community
    c = Community.query.get(community_id)
    if not c or not is_available():
        return {"adapted": caption, "changes": [], "warnings": []}

    result = _chat(
        system=(
            "Você é especialista em distribuição de conteúdo para comunidades digitais. "
            "Responda APENAS JSON válido, sem markdown."
        ),
        user=(
            f"Comunidade destino:\n{_ctx(c)}\n\n"
            f"Legenda original:\n{caption[:700]}\n\n"
            "Adapte a legenda para o contexto e tom desta comunidade. "
            "Preserve a essência, mas ajuste linguagem, referências e CTA.\n"
            'Responda: {"adapted": "legenda adaptada completa", '
            '"changes": ["o que foi alterado 1", "alteração 2"], '
            '"warnings": ["atenção: evite X nesta comunidade"]}'
        ),
        max_tokens=600,
    )

    data = result if result else {"adapted": caption, "changes": [], "warnings": []}
    _redis.setex(cache_key, _TTL_ADAPT, json.dumps(data))
    return data


# ---------------------------------------------------------------------------
# 4. Growth tips para a comunidade
# ---------------------------------------------------------------------------

def growth_tips(community_id: int, user_niche: str = "") -> dict:
    """
    Dicas de como crescer e distribuir conteúdo nesta comunidade.
    Retorna {"tips": [...], "do": [...], "dont": [...], "cta_suggestions": [...]}.
    """
    niche_hash = hashlib.md5(user_niche.encode()).hexdigest()[:6]
    cache_key = f"community_ai:growth:{community_id}:{niche_hash}"
    cached = _redis.get(cache_key)
    if cached:
        return json.loads(cached)

    from .models import Community
    c = Community.query.get(community_id)
    if not c or not is_available():
        return {"tips": [], "do": [], "dont": [], "cta_suggestions": []}

    niche_ctx = f"\nNicho do usuário: {user_niche}" if user_niche else ""
    result = _chat(
        system=(
            "Você é growth hacker especialista em comunidades digitais brasileiras. "
            "Responda APENAS JSON válido, sem markdown."
        ),
        user=(
            f"Comunidade:\n{_ctx(c)}{niche_ctx}\n\n"
            "Forneça dicas práticas e éticas de como crescer distribuindo "
            "conteúdo relevante nesta comunidade, sem spam.\n"
            'Responda: {"tips": ["dica principal 1", "dica 2"], '
            '"do": ["faça isso", "e isso"], '
            '"dont": ["não faça isso", "evite aquilo"], '
            '"cta_suggestions": ["CTA ideal 1", "CTA 2"]}'
        ),
        max_tokens=400,
    )

    data = result if result else {"tips": [], "do": [], "dont": [], "cta_suggestions": []}
    _redis.setex(cache_key, _TTL_GROWTH, json.dumps(data))
    return data


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def invalidate_community_ai_cache(community_id: int) -> None:
    for key in _redis.scan_iter(f"community_ai:*:{community_id}*"):
        _redis.delete(key)
