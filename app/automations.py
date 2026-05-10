"""
Postay Automations Engine — regras inteligentes baseadas em comportamento.
Funções puras: sem Flask, sem banco, sem efeitos colaterais.
"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta

from .analytics import post_score, best_time_analysis, period_comparison
from .recommendations import detect_patterns, client_profile, recommend_schedule

_TYPE_LABELS = {"photo": "Foto", "album": "Carrossel", "reels": "Reels", "story": "Story"}
_DAY_NAMES = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# ── Detecção de queda de engajamento ─────────────────────────────

def check_engagement_drop(posts_current: list, posts_previous: list) -> list[dict]:
    """Detecta quedas significativas de engajamento e gera alertas."""
    alerts = []
    if not posts_current:
        return alerts

    comparison = period_comparison(posts_current, posts_previous)
    delta = comparison["delta"]
    curr = comparison["current"]

    if delta.get("reach", 0) <= -30:
        alerts.append({
            "alert_type": "engagement_drop",
            "severity": "error",
            "title": "Queda de alcance detectada",
            "message": (
                f"Alcance caiu {abs(delta['reach']):.0f}% vs período anterior. "
                "Pode ser queda algorítmica ou inconsistência de conteúdo."
            ),
            "action": "Ver Analytics",
            "action_url": "/analytics",
        })

    if delta.get("saves", 0) <= -40 and curr.get("count", 0) >= 3:
        alerts.append({
            "alert_type": "saves_drop",
            "severity": "warning",
            "title": "Queda nos salvamentos",
            "message": (
                f"Salvamentos caíram {abs(delta['saves']):.0f}%. "
                "Tutoriais e dicas geram mais saves — tente variar o conteúdo."
            ),
            "action": "Ver Recomendações",
            "action_url": "/recommendations",
        })

    posted = [p for p in posts_current if p.instagram_media_id and (p.ig_reach or 0) > 0]
    if len(posted) >= 3:
        avg = sum(post_score(p) for p in posted) / len(posted)
        if avg < 1.0:
            alerts.append({
                "alert_type": "low_score",
                "severity": "warning",
                "title": "Score de engajamento abaixo do ideal",
                "message": (
                    f"Score médio {avg:.2f} — muito baixo. "
                    "Experimente novos formatos, horários ou tipos de conteúdo."
                ),
                "action": "Assistente IA",
                "action_url": "/ai",
            })

    return alerts


# ── Verificação de frequência ─────────────────────────────────────

def check_posting_frequency(posts: list, target_per_week: float = 3.0) -> list[dict]:
    """Verifica se o cliente está postando com a frequência ideal."""
    posted = [p for p in posts if p.status == "posted" and p.posted_at]
    if not posted:
        return [{
            "alert_type": "no_posts",
            "severity": "warning",
            "title": "Sem posts recentes",
            "message": "Nenhum post publicado nos últimos 30 dias. Consistência é essencial para crescimento.",
            "action": "Criar Post",
            "action_url": "/",
        }]

    dates = sorted(p.posted_at for p in posted)
    if len(dates) < 2:
        return []

    span_days = max(1, (dates[-1] - dates[0]).days)
    freq = len(posted) / max(1, span_days / 7)

    if freq < target_per_week * 0.5:
        return [{
            "alert_type": "frequency_low",
            "severity": "warning",
            "title": "Frequência de posts abaixo do recomendado",
            "message": (
                f"Você está postando {freq:.1f}x/semana. "
                f"O recomendado para crescimento contínuo é {target_per_week:.0f}x."
            ),
            "action": "Ver Calendário",
            "action_url": "/automations",
        }]

    return []


# ── Detecção de posts virais ───────────────────────────────────────

def detect_viral_posts(posts: list) -> list[dict]:
    """Identifica posts com performance excepcionalmente acima da média."""
    scored = [p for p in posts if p.instagram_media_id and (p.ig_reach or 0) > 0]
    if len(scored) < 3:
        return []

    all_scores = [post_score(p) for p in scored]
    avg = sum(all_scores) / len(all_scores)
    threshold = max(avg * 2.0, 10.0)

    viral = [
        {
            "post_id": p.id,
            "filename": p.image_filename,
            "score": post_score(p),
            "posted_at": p.posted_at,
            "ig_reach": p.ig_reach or 0,
        }
        for p in scored if post_score(p) >= threshold
    ]
    viral.sort(key=lambda x: -x["score"])
    return viral[:3]


# ── Geração de todos os alertas ───────────────────────────────────

def generate_smart_alerts(posts_current: list, posts_previous: list) -> list[dict]:
    """Combina todos os alertas inteligentes em uma lista ordenada por severidade."""
    alerts = []
    alerts.extend(check_engagement_drop(posts_current, posts_previous))
    alerts.extend(check_posting_frequency(posts_current))

    viral = detect_viral_posts(posts_current)
    if viral:
        alerts.append({
            "alert_type": "viral_detected",
            "severity": "success",
            "title": f"Post viral detectado! 🔥",
            "message": (
                f"Um post teve score {viral[0]['score']:.1f} — muito acima da média. "
                "Analise o que funcionou e repita a fórmula."
            ),
            "action": "Ver Analytics",
            "action_url": "/analytics",
        })

    severity_order = {"error": 0, "warning": 1, "success": 2, "info": 3}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 9))
    return alerts


# ── Sugestão de frequência ────────────────────────────────────────

def suggest_optimal_frequency(posts: list) -> dict:
    """Recomenda frequência semanal de posts baseada no histórico de performance."""
    profile = client_profile(posts)
    freq = profile.get("freq_per_week", 0)
    avg_score = profile.get("avg_score", 0)

    if avg_score >= 8:
        recommended = max(freq, 5.0)
        rationale = "Engajamento excelente — aumente a frequência para maximizar alcance."
    elif avg_score >= 4:
        recommended = max(freq, 3.0)
        rationale = "Bom engajamento. Mantenha 3-5 posts/semana para crescimento constante."
    else:
        recommended = min(max(freq, 2.0), 3.0)
        rationale = "Foque em qualidade antes de quantidade. 2-3 posts bem feitos > 7 mediocres."

    return {
        "current_freq": round(freq, 1),
        "recommended_freq": round(recommended, 1),
        "rationale": rationale,
        "level": profile.get("level", "iniciante"),
    }


# ── Sugestão de próximo conteúdo ──────────────────────────────────

def suggest_next_content(posts: list) -> dict:
    """Sugere o próximo tipo de conteúdo a postar com base no histórico."""
    from .analytics import type_performance
    types = type_performance(posts)
    patterns = detect_patterns(posts)

    if not types:
        return {
            "suggested_type": "reels",
            "type_label": "Reels",
            "rationale": "Reels têm o maior alcance orgânico no Instagram atualmente.",
            "content_ideas": [
                "Tutorial rápido (30-60s) sobre o seu nicho",
                "Bastidores do seu trabalho ou rotina",
                "Dica prática que resolve um problema comum",
                "Tendência do momento adaptada ao seu nicho",
            ],
        }

    best = types[0]
    suggested_type = best["type"]
    rationale = f"{best['label']}s têm seu melhor score ({best['avg_score']:.1f}). Continue investindo."

    if patterns.get("format_bias"):
        bias = patterns["format_bias"]
        alts = [t for t in ["reels", "album", "photo"] if t != bias["type"]]
        if alts:
            suggested_type = alts[0]
            lbl = _TYPE_LABELS.get(suggested_type, suggested_type)
            rationale = (
                f"Você foca muito em {bias['label']} ({bias['pct']:.0f}%). "
                f"Experimente {lbl}s para atingir novos públicos."
            )

    lbl = _TYPE_LABELS.get(suggested_type, suggested_type)
    return {
        "suggested_type": suggested_type,
        "type_label": lbl,
        "rationale": rationale,
        "content_ideas": [
            f"Tutorial em {lbl} sobre tema central do seu nicho",
            "Bastidores: mostre o processo por trás do trabalho",
            "Conteúdo de valor: resolva um problema real do seu público",
            "Tendência: adapte formato popular ao seu nicho",
        ],
    }


# ── Calendário automático ─────────────────────────────────────────

def auto_calendar_suggestions(posts: list, days_ahead: int = 7) -> list[dict]:
    """
    Gera sugestões de agenda para os próximos N dias usando os melhores horários históricos.
    """
    bt = best_time_analysis(posts)
    best_hours = [h for h, _ in bt.get("best_hours", [])] or [9, 17]
    best_days_set = {d for d, _ in bt.get("best_weekdays", [])} or {0, 1, 2, 3, 4}

    from zoneinfo import ZoneInfo
    BRT = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(timezone.utc).astimezone(BRT)

    suggestions = []
    for i in range(1, days_ahead + 1):
        date = now + timedelta(days=i)
        weekday = date.weekday()
        is_optimal = weekday in best_days_set
        hour = best_hours[0] if is_optimal else (best_hours[1] if len(best_hours) > 1 else best_hours[0])
        suggestions.append({
            "date": date.strftime("%Y-%m-%d"),
            "weekday": weekday,
            "day_name": _DAY_NAMES[weekday],
            "hour": hour,
            "time_str": f"{hour:02d}:00",
            "is_optimal": is_optimal,
            "priority": "alta" if is_optimal else "normal",
        })

    return suggestions


# ── Progresso de metas ────────────────────────────────────────────

def check_goal_progress(goal_type: str, target_value: float, deadline, posts: list) -> dict:
    """
    Calcula progresso de uma meta a partir dos posts publicados.
    goal_type: reach | likes | posts_week | score
    """
    now = datetime.now(timezone.utc)
    posted = [p for p in posts if p.status == "posted"]

    if goal_type == "reach":
        current = float(sum(p.ig_reach or 0 for p in posted))
    elif goal_type == "likes":
        current = float(sum(p.ig_likes or 0 for p in posted))
    elif goal_type == "posts_week":
        dates = [p.posted_at for p in posted if p.posted_at]
        if len(dates) >= 2:
            span = max(1, (max(dates) - min(dates)).days)
            current = round(len(posted) / max(1, span / 7), 1)
        else:
            current = float(len(posted))
    elif goal_type == "score":
        scored = [p for p in posted if p.instagram_media_id and (p.ig_reach or 0) > 0]
        current = round(sum(post_score(p) for p in scored) / len(scored), 2) if scored else 0.0
    else:
        current = 0.0

    progress_pct = min(100.0, round(current / max(target_value, 0.01) * 100, 1))

    days_remaining = None
    on_track = True
    if deadline:
        dl = deadline if deadline.tzinfo else deadline.replace(tzinfo=timezone.utc)
        days_remaining = max(0, (dl - now).days)
        if days_remaining > 0 and progress_pct < 100:
            # Tempo decorrido em relação ao prazo total
            if goal_type in ("reach", "likes"):
                needed_rate = (target_value - current) / days_remaining
                avg_daily = current / max(1, 30)
                on_track = avg_daily >= needed_rate * 0.7
            else:
                total_days = days_remaining + 30
                elapsed_pct = 30 / total_days * 100
                on_track = progress_pct >= elapsed_pct * 0.7

    return {
        "current_value": current,
        "progress_pct": progress_pct,
        "on_track": on_track,
        "days_remaining": days_remaining,
        "is_achieved": progress_pct >= 100,
    }
