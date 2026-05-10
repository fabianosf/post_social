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


# ═══════════════════════════════════════════════════════════════════
# FASE 7 — GERAÇÃO DE CONTEÚDO
# ═══════════════════════════════════════════════════════════════════

# ── Sistema de nichos ─────────────────────────────────────────────

_NICHES: dict[str, dict] = {
    "fitness": {
        "label": "Fitness & Saúde",
        "audience": "pessoas que buscam emagrecimento, saúde e qualidade de vida",
        "pain_points": "falta de tempo, dificuldade de emagrecer, desmotivação, falta de disciplina",
        "desires": "corpo definido, energia, autoestima, hábitos saudáveis",
        "pillars": ["dica rápida", "mito x verdade", "treino", "receita fit", "motivação"],
        "tone": "motivador e direto",
    },
    "gastronomia": {
        "label": "Gastronomia & Culinária",
        "audience": "pessoas que amam cozinhar, foodies, aprendizes de culinária",
        "pain_points": "falta de criatividade, receitas difíceis, ingredientes caros",
        "desires": "receitas fáceis, elogios, impressionar, economizar tempo",
        "pillars": ["receita rápida", "dica de cozinha", "ingrediente do dia", "erro comum", "variação"],
        "tone": "acolhedor e apetitoso",
    },
    "moda": {
        "label": "Moda & Estilo",
        "audience": "pessoas que se preocupam com aparência, tendências e expressão pessoal",
        "pain_points": "não saber combinar roupas, falta de verba, insegurança com estilo",
        "desires": "looks elegantes, autoconfiança, ser elogiada, tendências acessíveis",
        "pillars": ["look do dia", "como combinar", "tendência", "guarda-roupa cápsula", "dica de compra"],
        "tone": "confiante e inspirador",
    },
    "negocios": {
        "label": "Negócios & Empreendedorismo",
        "audience": "empreendedores, freelancers, donos de pequenos negócios",
        "pain_points": "falta de clientes, gestão financeira, marketing digital, tempo",
        "desires": "escalar o negócio, mais vendas, liberdade financeira, reconhecimento",
        "pillars": ["estratégia", "erro comum", "case de sucesso", "dica prática", "motivação"],
        "tone": "profissional e estratégico",
    },
    "educacao": {
        "label": "Educação & Cursos",
        "audience": "estudantes, profissionais em transição, pessoas que buscam crescimento",
        "pain_points": "falta de tempo para estudar, dificuldade de foco, conteúdo complexo",
        "desires": "aprender rápido, certificações, nova carreira, crescimento profissional",
        "pillars": ["conceito simplificado", "dica de estudo", "mapa mental", "quiz", "motivação"],
        "tone": "didático e acessível",
    },
    "tecnologia": {
        "label": "Tecnologia & IA",
        "audience": "profissionais de tech, entusiastas, pessoas curiosas sobre o futuro",
        "pain_points": "velocidade das mudanças, não saber por onde começar, jargões",
        "desires": "ficar atualizado, usar IA no trabalho, produtividade, diferencial competitivo",
        "pillars": ["novidade", "tutorial", "comparativo", "opinião", "dica de produtividade"],
        "tone": "moderno e acessível",
    },
    "beleza": {
        "label": "Beleza & Skincare",
        "audience": "mulheres que se preocupam com aparência, skincare e autocuidado",
        "pain_points": "acne, pele opaca, produtos caros, rotinas complexas, cabelo",
        "desires": "pele perfeita, autoestima, produtos eficientes, rotina prática",
        "pillars": ["rotina de skincare", "produto favorito", "antes e depois", "dica rápida", "ingrediente"],
        "tone": "acolhedor e confiante",
    },
    "financas": {
        "label": "Finanças Pessoais",
        "audience": "pessoas que querem sair das dívidas, investir ou ter reserva financeira",
        "pain_points": "endividamento, falta de controle, medo de investir, salário baixo",
        "desires": "reserva de emergência, independência financeira, primeiro investimento",
        "pillars": ["dica de economia", "mito financeiro", "simulação", "investimento para iniciantes", "hábito"],
        "tone": "didático e motivador",
    },
    "viagem": {
        "label": "Viagem & Turismo",
        "audience": "viajantes, mochileiros, famílias que planejam férias",
        "pain_points": "custo alto, falta de planejamento, destinos desconhecidos",
        "desires": "viajar mais, economizar, experiências únicas, roteiros prontos",
        "pillars": ["roteiro", "dica de economia", "destino", "erro de viagem", "experiência pessoal"],
        "tone": "aventureiro e inspirador",
    },
    "geral": {
        "label": "Geral",
        "audience": "público amplo",
        "pain_points": "desafios do cotidiano",
        "desires": "melhorar a vida, aprender algo novo",
        "pillars": ["dica prática", "reflexão", "motivação", "curiosidade", "storytelling"],
        "tone": "autêntico e acessível",
    },
}

NICHES_LIST = [{"key": k, "label": v["label"]} for k, v in _NICHES.items()]

_TONES = {
    "inspirador":   "motivador, emocional, usa storytelling e transformação",
    "informativo":  "educativo, baseado em dados e fatos, clareza acima de tudo",
    "humoristico":  "leve, divertido, relatable, usa humor autêntico sem forçar",
    "vendas":       "direto ao ponto, benefícios claros, urgência, CTA forte",
    "storytelling": "narrativa pessoal, vulnerável, arco dramático, conexão emocional",
}


def _niche_ctx(niche: str) -> str:
    """Retorna contexto de nicho para enriquecer prompts."""
    d = _NICHES.get(niche, _NICHES["geral"])
    return (
        f"Nicho: {d['label']}\n"
        f"Público: {d['audience']}\n"
        f"Dores: {d['pain_points']}\n"
        f"Desejos: {d['desires']}\n"
        f"Tom: {d.get('tone', 'autêntico')}"
    )


# ── Geração de legenda completa ───────────────────────────────────

def generate_caption(
    niche: str,
    topic: str,
    post_type: str = "photo",
    tone: str = "informativo",
    goal: str = "engajamento",
    length: str = "media",
) -> dict | None:
    """
    Gera legenda completa com hook, desenvolvimento e CTA.
    length: curta (~50 palavras) | media (~100) | longa (~200)
    """
    length_map = {"curta": "~50 palavras", "media": "~100-120 palavras", "longa": "~180-220 palavras"}
    tone_desc = _TONES.get(tone, tone)

    system = (
        "Você é um copywriter especialista em Instagram brasileiro com foco em crescimento orgânico. "
        "Cria legendas que convertem e geram engajamento real. Retorne JSON válido em português."
    )
    user = (
        f"{_niche_ctx(niche)}\n\n"
        f"Tipo de post: {post_type}\n"
        f"Tema/tópico: {topic}\n"
        f"Tom: {tone_desc}\n"
        f"Objetivo: {goal}\n"
        f"Tamanho: {length_map.get(length, length_map['media'])}\n\n"
        'Retorne JSON: {"caption": "legenda completa com quebras de linha e emojis", '
        '"hook": "apenas a primeira linha", '
        '"cta": "apenas o CTA final", '
        '"hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5", '
        '"tips": ["por que este hook funciona", "como adaptar para o seu perfil"]}'
    )
    return _chat(system, user, max_tokens=1000)


# ── Geração de hooks variados ─────────────────────────────────────

def generate_hooks(niche: str, topic: str, quantity: int = 5) -> dict | None:
    """
    Gera N variações de hook para o mesmo tema em estilos diferentes.
    """
    system = (
        "Você é especialista em hooks virais para Instagram brasileiro. "
        "Cria primeiras linhas que param o scroll. Retorne JSON válido em português."
    )
    user = (
        f"{_niche_ctx(niche)}\n"
        f"Tema: {topic}\n\n"
        f"Gere {quantity} hooks diferentes em estilos variados:\n"
        'Retorne JSON: {"hooks": ['
        '{"hook": "...", "style": "pergunta|choque|curiosidade|número|promessa|polêmica", "why": "por que funciona"}'
        '], "best_hook": "o mais forte dos cinco"}'
    )
    return _chat(system, user, max_tokens=700)


# ── Geração de títulos / headlines ────────────────────────────────

def generate_titles(niche: str, topic: str, post_type: str = "reels") -> dict | None:
    """
    Gera títulos/headlines para Reels, Carrosséis e Stories.
    """
    system = (
        "Você cria títulos e headlines para Instagram brasileiro que geram cliques e salvamentos. "
        "Retorne JSON válido em português."
    )
    user = (
        f"{_niche_ctx(niche)}\n"
        f"Tipo de post: {post_type}\n"
        f"Tema: {topic}\n\n"
        'Retorne JSON: {"titles": ['
        '{"title": "...", "format": "lista|tutorial|revelação|pergunta|polêmica", "appeal": "por que atrai"}'
        '], "best_title": "o mais forte"}'
    )
    return _chat(system, user, max_tokens=600)


# ── Reescrita e melhoria de legenda ──────────────────────────────

def rewrite_caption(original: str, goal: str = "engajamento", tone: str = "informativo") -> dict | None:
    """
    Reescreve uma legenda existente mantendo a essência mas melhorando estrutura, hook e CTA.
    """
    tone_desc = _TONES.get(tone, tone)
    system = (
        "Você é editor-chefe de conteúdo para Instagram brasileiro. "
        "Melhora legendas preservando a voz do criador. Retorne JSON válido em português."
    )
    user = (
        f"Legenda original:\n{original[:700]}\n\n"
        f"Objetivo: {goal}\n"
        f"Tom desejado: {tone_desc}\n\n"
        'Retorne JSON: {"rewritten": "nova versão completa", '
        '"changes": ["mudança 1", "mudança 2", "mudança 3"], '
        '"hook_before": "hook original", '
        '"hook_after": "hook melhorado", '
        '"score_before": 5, "score_after": 8, '
        '"explanation": "por que as mudanças melhoram o resultado"}'
    )
    return _chat(system, user, max_tokens=1000)


# ── Otimização de retenção ────────────────────────────────────────

def optimize_retention(caption: str) -> dict | None:
    """
    Reestrutura a legenda usando técnicas de retenção: padrão de interrupção,
    gap de curiosidade, micro-compromisso, prova social, cliffhanger.
    """
    system = (
        "Você é especialista em retenção e copywriting para Instagram. "
        "Aplique técnicas psicológicas de retenção sem perder autenticidade. "
        "Retorne JSON válido em português."
    )
    user = (
        f"Legenda para otimizar:\n{caption[:700]}\n\n"
        'Retorne JSON: {"optimized": "legenda reestruturada", '
        '"techniques_used": ["padrão de interrupção", "gap de curiosidade"], '
        '"structure_tips": ["Use quebra de linha após o hook", "Adicione micro-comprometimento"], '
        '"retention_score_before": 5, "retention_score_after": 8}'
    )
    return _chat(system, user, max_tokens=900)


# ── Sugestões de viralização ──────────────────────────────────────

def suggest_viralization(caption: str, niche: str = "geral") -> dict | None:
    """
    Analisa o conteúdo e sugere táticas específicas para maximizar o potencial viral.
    """
    system = (
        "Você é especialista em crescimento viral no Instagram brasileiro. "
        "Sugira táticas práticas e específicas para viralização. Retorne JSON válido em português."
    )
    user = (
        f"{_niche_ctx(niche)}\n\n"
        f"Conteúdo:\n{caption[:600]}\n\n"
        'Retorne JSON: {"tactics": ['
        '{"tactic": "nome da tática", "implementation": "como aplicar especificamente", "impact": "alto|medio|baixo"}'
        '], "viral_elements_missing": ["...", "..."], '
        '"best_posting_time": "dia e horário ideal", '
        '"collaboration_idea": "ideia de collab para amplificar", '
        '"viral_score": 65}'
    )
    return _chat(system, user, max_tokens=800)


# ── Geração de calendário de conteúdo ────────────────────────────

def generate_content_calendar(
    niche: str,
    posts_per_week: int = 3,
    weeks: int = 2,
    goals: list | None = None,
) -> dict | None:
    """
    Gera calendário editorial completo com temas, tipos, hooks e CTAs.
    """
    d = _NICHES.get(niche, _NICHES["geral"])
    pillars = ", ".join(d.get("pillars", ["dica", "motivação", "curiosidade"]))
    goals_str = ", ".join(goals) if goals else "engajamento, crescimento de seguidores"

    system = (
        "Você é estrategista de conteúdo para Instagram brasileiro. "
        "Cria calendários editoriais completos e variados. Retorne JSON válido em português."
    )
    user = (
        f"Nicho: {d['label']}\n"
        f"Pilares de conteúdo: {pillars}\n"
        f"Objetivos: {goals_str}\n"
        f"Posts por semana: {posts_per_week}\n"
        f"Semanas: {weeks}\n\n"
        "Crie um calendário com dias distribuídos ao longo da semana (Seg, Qua, Sex para 3x/semana etc).\n"
        'Retorne JSON: {"calendar_theme": "tema geral do período", '
        '"weeks": [{"week_number": 1, "weekly_focus": "tema da semana", '
        '"posts": [{"day": "Segunda", "type": "reels", "hook": "...", '
        '"topic": "...", "caption_idea": "desenvolvimento em 1 frase", "cta": "...", '
        '"hashtag_theme": "categoria das hashtags"}]}], '
        '"general_tips": ["dica estratégica 1", "dica estratégica 2"]}'
    )
    return _chat(system, user, max_tokens=2500)
