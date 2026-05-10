"""
Postay AI Service — wrapper OpenAI/Groq para análise de conteúdo.
Suporta: AI_PROVIDER=openai (padrão) ou AI_PROVIDER=groq (gratuito).
Graceful degradation: retorna None quando não configurado.
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_AI_PROVIDER = os.environ.get("AI_PROVIDER", "openai")


def _client():
    """Lazy-init do cliente OpenAI-compatible."""
    try:
        from openai import OpenAI
        if _AI_PROVIDER == "groq":
            key = os.environ.get("GROQ_API_KEY", "")
            if not key:
                return None
            return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
        key = os.environ.get("OPENAI_API_KEY", "")
        return OpenAI(api_key=key) if key else None
    except ImportError:
        return None


def _model() -> str:
    if _AI_PROVIDER == "groq":
        return "llama-3.1-8b-instant"
    return "gpt-4o-mini"


def is_available() -> bool:
    """True se a integração AI está configurada."""
    if _AI_PROVIDER == "groq":
        return bool(os.environ.get("GROQ_API_KEY"))
    return bool(os.environ.get("OPENAI_API_KEY"))


def _chat(system: str, user: str, max_tokens: int = 700) -> dict | None:
    """
    Faz chamada ao LLM e retorna dict JSON parseado.
    Tenta 3 vezes com backoff; retorna None em erro.
    """
    cl = _client()
    if cl is None:
        return None

    for attempt in range(3):
        try:
            resp = cl.chat.completions.create(
                model=_model(),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                logger.warning(f"ai_service._chat falhou: {e}")
                return None


# ── Análise de legenda ────────────────────────────────────────────

def analyze_caption(caption: str) -> dict | None:
    """
    Analisa qualidade da legenda: pontos fortes, melhorias, hook, emoção.
    Retorna dict ou None.
    """
    if not caption or len(caption.strip()) < 10:
        return None

    system = (
        "Você é especialista em marketing de conteúdo para Instagram brasileiro. "
        "Analise legendas e retorne JSON válido conforme solicitado. "
        "Responda sempre em português do Brasil."
    )
    user = (
        f"Analise esta legenda do Instagram:\n\n{caption[:700]}\n\n"
        'Retorne JSON: {"strengths": ["...", "..."], "improvements": ["...", "..."], '
        '"hook_score": 7, "readability_score": 8, "has_cta": true, '
        '"emotion": "curiosidade", "suggested_hook": "..."}'
    )
    return _chat(system, user, max_tokens=650)


# ── Análise de hook ────────────────────────────────────────────────

def analyze_hook(caption: str) -> dict | None:
    """
    Avalia a primeira linha da legenda como hook de retenção.
    """
    if not caption:
        return None
    first_line = caption.split("\n")[0][:250].strip()
    if len(first_line) < 5:
        return None

    system = (
        "Você é especialista em hooks para conteúdo do Instagram brasileiro. "
        "Avalie a primeira linha da legenda. Retorne JSON válido em português."
    )
    user = (
        f"Hook (primeira linha): {first_line}\n\n"
        'Retorne JSON: {"hook_score": 7, '
        '"type": "pergunta", '
        '"is_effective": true, '
        '"why": "...", '
        '"improved_version": "...", '
        '"alternative_hooks": ["...", "...", "..."]}'
    )
    return _chat(system, user, max_tokens=450)


# ── Sugestão de hashtags ──────────────────────────────────────────

def suggest_hashtags_ai(caption: str, niche: str = "", post_type: str = "photo") -> dict | None:
    """
    Sugere hashtags em 3 camadas: nicho, populares, amplas.
    """
    system = (
        "Você é especialista em hashtags para Instagram brasileiro. "
        "Sugira hashtags reais e relevantes usadas no Brasil. Retorne JSON válido."
    )
    user = (
        f"Nicho: {niche or 'geral'}\n"
        f"Tipo de post: {post_type}\n"
        f"Legenda: {caption[:400] if caption else 'não informada'}\n\n"
        'Retorne JSON: {"niche_tags": ["#tag1", "#tag2"], '
        '"popular_tags": ["#tag3", "#tag4"], '
        '"broad_tags": ["#tag5", "#tag6"], '
        '"all_hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5 #tag6"}'
    )
    return _chat(system, user, max_tokens=500)


# ── Sugestão de CTA ───────────────────────────────────────────────

def suggest_cta_ai(caption: str, goal: str = "engajamento") -> dict | None:
    """
    Cria CTAs em português baseados no conteúdo e objetivo.
    goal: engajamento | seguidores | vendas | salvamentos
    """
    system = (
        "Você é especialista em copywriting para Instagram brasileiro. "
        "Crie CTAs autênticos que geram engajamento real. Retorne JSON válido em português."
    )
    user = (
        f"Objetivo: {goal}\n"
        f"Legenda: {caption[:400] if caption else 'não informada'}\n\n"
        'Retorne JSON: {"ctas": ["...", "...", "...", "...", "..."], '
        '"best_cta": "...", "reasoning": "..."}'
    )
    return _chat(system, user, max_tokens=450)


# ── Score de viralização ──────────────────────────────────────────

def virality_score_ai(caption: str, metrics: dict) -> dict | None:
    """
    Pontua potencial viral combinando análise de conteúdo + métricas reais.
    """
    system = (
        "Você analisa potencial viral de posts no Instagram brasileiro. "
        "Combine dados reais com análise de conteúdo. Retorne JSON válido."
    )
    user = (
        f"Legenda: {caption[:500] if caption else 'sem legenda'}\n\n"
        f"Métricas reais:\n"
        f"- Curtidas: {metrics.get('likes', 0)}\n"
        f"- Comentários: {metrics.get('comments', 0)}\n"
        f"- Salvamentos: {metrics.get('saves', 0)}\n"
        f"- Alcance: {metrics.get('reach', 0)}\n\n"
        'Retorne JSON: {"virality_score": 72, '
        '"viral_factors": ["...", "..."], '
        '"missing_elements": ["...", "..."], '
        '"viral_tip": "..."}'
    )
    return _chat(system, user, max_tokens=400)


# ── Previsão de performance ───────────────────────────────────────

def predict_performance_ai(post_summary: dict, history: dict) -> dict | None:
    """
    Prevê métricas de performance baseado no histórico do cliente.
    """
    system = (
        "Você é analista de dados do Instagram. Preveja performance de forma realista e conservadora. "
        "Retorne JSON válido em português."
    )
    user = (
        f"Histórico da conta (30 dias):\n"
        f"- Posts publicados: {history.get('count', 0)}\n"
        f"- Alcance médio por post: {history.get('avg_reach', 0)}\n"
        f"- Score médio de engajamento: {history.get('avg_score', 0):.1f}\n"
        f"- Melhor formato: {history.get('best_type', 'photo')}\n"
        f"- Melhor horário: {history.get('best_hour', 12)}h\n\n"
        f"Novo post:\n"
        f"- Tipo: {post_summary.get('type', 'photo')}\n"
        f"- Horário agendado: {post_summary.get('hour', 12)}h\n"
        f"- Tem legenda: {post_summary.get('has_caption', False)}\n"
        f"- Tem hashtags: {post_summary.get('has_hashtags', False)}\n\n"
        'Retorne JSON: {"expected_reach": 500, "expected_likes": 40, '
        '"expected_comments": 5, "expected_saves": 8, '
        '"confidence": 7, "score_prediction": 4.2, "tips": ["...", "..."]}'
    )
    return _chat(system, user, max_tokens=500)


# ── Insights gerais da conta ──────────────────────────────────────

def generate_ai_insights(stats: dict) -> dict | None:
    """
    Gera insights estratégicos sobre o desempenho geral da conta.
    stats: count, total_reach, total_likes, total_saves, avg_score,
           reach_growth, best_type, consistency
    """
    system = (
        "Você é consultor de crescimento para criadores no Instagram brasileiro. "
        "Analise os dados e gere insights estratégicos concisos e acionáveis. "
        "Retorne JSON válido em português."
    )
    user = (
        f"Dados da conta (últimos 30 dias):\n"
        f"- Posts publicados: {stats.get('count', 0)}\n"
        f"- Alcance total: {stats.get('total_reach', 0)}\n"
        f"- Curtidas totais: {stats.get('total_likes', 0)}\n"
        f"- Salvamentos totais: {stats.get('total_saves', 0)}\n"
        f"- Score médio de engajamento: {stats.get('avg_score', 0):.1f}\n"
        f"- Crescimento de alcance vs período anterior: {stats.get('reach_growth', 0):.1f}%\n"
        f"- Melhor formato: {stats.get('best_type', 'desconhecido')}\n"
        f"- Consistência de publicação: {stats.get('consistency', 'desconhecida')}\n\n"
        'Retorne JSON: {"insights": ['
        '{"icon": "📈", "text": "...", "action": "...", "priority": "alta"},'
        '{"icon": "💡", "text": "...", "action": "...", "priority": "media"}'
        '], "summary": "...", "growth_potential": "alto"}'
    )
    return _chat(system, user, max_tokens=900)
