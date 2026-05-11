"""
Postay — Growth Analytics Engine (Fase 9)
Previsão de crescimento, benchmark, score e insights estratégicos.
Funções puras: sem Flask, sem banco, sem efeitos colaterais.
"""

from collections import defaultdict
from datetime import datetime, timezone

# ── Benchmarks reais do Instagram 2024 ───────────────────────────
_BM = {
    "reach_per_post":  {"baixo": 200,   "medio": 800,   "alto": 3000,  "viral": 10000},
    "engagement_rate": {"baixo": 0.01,  "medio": 0.03,  "alto": 0.06,  "viral": 0.12},
    "posts_per_week":  {"baixo": 1,     "medio": 3,     "alto": 5,     "viral": 7},
    "saves_ratio":     {"baixo": 0.005, "medio": 0.02,  "alto": 0.05,  "viral": 0.10},
}


def _avg(iterable) -> float:
    vals = [v for v in iterable if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _scored(posts: list) -> list:
    return [p for p in posts if p.instagram_media_id]


# ── Score de crescimento ──────────────────────────────────────────

def growth_score(posts_30: list, posts_prev_30: list) -> dict:
    """Score composto 0-100 de saúde e crescimento."""
    from .analytics import post_score as _post_score

    cur = _scored(posts_30)
    prev = _scored(posts_prev_30)

    # 1. Crescimento de alcance (30 pts)
    cur_reach  = _avg(p.ig_reach or 0 for p in cur)
    prev_reach = _avg(p.ig_reach or 0 for p in prev)
    reach_growth_pct = (cur_reach - prev_reach) / max(prev_reach, 1) * 100 if prev_reach else 0
    reach_pts = min(30.0, max(0.0, 15 + reach_growth_pct * 0.25))

    # 2. Taxa de engajamento (25 pts)
    total_reach = sum(p.ig_reach or 1 for p in cur) or 1
    eng_w = sum(
        (p.ig_likes or 0) + (p.ig_comments or 0) * 3 + (p.ig_saves or 0) * 5
        for p in cur
    )
    eng_rate = eng_w / total_reach
    eng_pts = min(25.0, eng_rate * 400)

    # 3. Consistência de publicação (20 pts)
    ppw = len(posts_30) / 4.3
    consistency_pts = min(20.0, ppw / 5 * 20)

    # 4. Tendência recente (15 pts) — últimos 15 dias vs anteriores
    half = max(1, len(cur) // 2)
    recent_reach = _avg(p.ig_reach or 0 for p in cur[half:]) if cur[half:] else 0
    older_reach  = _avg(p.ig_reach or 0 for p in cur[:half])
    trend_growth = (recent_reach - older_reach) / max(older_reach, 1) * 100 if older_reach else 0
    trend_pts = min(15.0, max(0.0, 7.5 + trend_growth * 0.15))

    # 5. Qualidade média dos posts (10 pts)
    avg_ps = _avg(_post_score(p) for p in cur)
    quality_pts = min(10.0, avg_ps / 10 * 10)

    total = round(reach_pts + eng_pts + consistency_pts + trend_pts + quality_pts, 1)
    total = max(0.0, min(100.0, total))

    label = "Excelente" if total >= 75 else "Bom" if total >= 55 else "Regular" if total >= 35 else "Baixo"
    color = "#4ade80" if total >= 75 else "#60a5fa" if total >= 55 else "#fbbf24" if total >= 35 else "#f87171"

    return {
        "score": total,
        "label": label,
        "color": color,
        "components": {
            "reach_growth":  round(reach_pts, 1),
            "engagement":    round(eng_pts, 1),
            "consistency":   round(consistency_pts, 1),
            "trend":         round(trend_pts, 1),
            "post_quality":  round(quality_pts, 1),
        },
        "metrics": {
            "reach_growth_pct": round(reach_growth_pct, 1),
            "engagement_rate_pct": round(eng_rate * 100, 2),
            "posts_per_week": round(ppw, 1),
            "avg_post_score": round(avg_ps, 2),
        },
    }


# ── Previsão de crescimento ───────────────────────────────────────

def growth_prediction(posts: list, days_ahead: int = 30) -> dict:
    """Regressão linear sobre alcance semanal → projeção dos próximos dias."""
    from .analytics import growth_trend

    week_data: dict[int, list] = defaultdict(list)
    now = datetime.now(timezone.utc)
    for p in posts:
        if not p.ig_reach or not p.posted_at:
            continue
        dt = p.posted_at if p.posted_at.tzinfo else p.posted_at.replace(tzinfo=timezone.utc)
        wk = (now - dt).days // 7
        week_data[wk].append(p.ig_reach)

    if len(week_data) < 2:
        base = _avg(p.ig_reach or 0 for p in posts if p.ig_reach)
        return {
            "days_ahead": days_ahead,
            "predicted_avg_reach": round(base),
            "predicted_total_reach": round(base * (days_ahead / 7) * 2),
            "trend_direction": "stable",
            "confidence": 3,
            "weekly_forecast": [],
            "message": "Dados insuficientes — continue publicando para previsões mais precisas",
        }

    sorted_weeks = sorted(week_data.keys(), reverse=True)
    daily_data = [{"reach": _avg(week_data[w])} for w in sorted_weeks]
    trend = growth_trend(daily_data)
    slope = trend["slope"]
    direction = trend["trend"]

    cur_week_avg = _avg(week_data[sorted_weeks[0]])
    weeks_ahead = max(1, days_ahead // 7)

    weekly_forecast = [
        {"week": i, "projected_reach": max(0, round(cur_week_avg + slope * i))}
        for i in range(1, weeks_ahead + 1)
    ]
    predicted_avg = max(0, round(cur_week_avg + slope * weeks_ahead / 2))
    confidence = min(9, max(3, len(week_data)))

    msgs = {
        "up":     "Crescimento acelerado detectado — mantenha o ritmo!",
        "down":   "Queda detectada — revise horários, formato e frequência",
        "stable": "Tendência estável — aumente frequência para escalar",
    }

    return {
        "days_ahead": days_ahead,
        "predicted_avg_reach": predicted_avg,
        "predicted_total_reach": predicted_avg * weeks_ahead,
        "trend_direction": direction,
        "trend_slope": slope,
        "confidence": confidence,
        "weekly_forecast": weekly_forecast,
        "message": msgs.get(direction, "Tendência positiva de crescimento"),
    }


# ── Benchmark vs plataforma ───────────────────────────────────────

def benchmark_data(posts_30: list) -> dict:
    """Compara métricas com benchmarks reais do Instagram 2024."""
    scored = _scored(posts_30)
    if not scored:
        return {"error": "Nenhum post com métricas disponível"}

    avg_reach = _avg(p.ig_reach or 0 for p in scored)
    total_reach = sum(p.ig_reach or 1 for p in scored) or 1
    avg_saves = _avg(p.ig_saves or 0 for p in scored)
    eng_w = sum(
        (p.ig_likes or 0) + (p.ig_comments or 0) * 3 + (p.ig_saves or 0) * 5
        for p in scored
    )
    eng_rate = eng_w / total_reach
    ppw = len(posts_30) / 4.3
    saves_ratio = avg_saves / max(avg_reach, 1)

    def _pct(val, field):
        lv = _BM[field]
        if val >= lv["viral"]:  return 95
        if val >= lv["alto"]:   return 75
        if val >= lv["medio"]:  return 50
        if val >= lv["baixo"]:  return 25
        return 10

    def _lvl(val, field):
        lv = _BM[field]
        if val >= lv["viral"]:  return "Top 5%"
        if val >= lv["alto"]:   return "Acima da média"
        if val >= lv["medio"]:  return "Na média"
        if val >= lv["baixo"]:  return "Abaixo da média"
        return "Muito abaixo"

    metrics = {
        "reach_per_post": {
            "value": round(avg_reach),
            "percentile": _pct(avg_reach, "reach_per_post"),
            "level": _lvl(avg_reach, "reach_per_post"),
            "platform_avg": _BM["reach_per_post"]["medio"],
        },
        "engagement_rate": {
            "value": round(eng_rate * 100, 2),
            "percentile": _pct(eng_rate, "engagement_rate"),
            "level": _lvl(eng_rate, "engagement_rate"),
            "platform_avg": round(_BM["engagement_rate"]["medio"] * 100, 1),
        },
        "posts_per_week": {
            "value": round(ppw, 1),
            "percentile": _pct(ppw, "posts_per_week"),
            "level": _lvl(ppw, "posts_per_week"),
            "platform_avg": _BM["posts_per_week"]["medio"],
        },
        "saves_ratio": {
            "value": round(saves_ratio * 100, 2),
            "percentile": _pct(saves_ratio, "saves_ratio"),
            "level": _lvl(saves_ratio, "saves_ratio"),
            "platform_avg": round(_BM["saves_ratio"]["medio"] * 100, 1),
        },
    }

    overall = round(_avg(m["percentile"] for m in metrics.values()))
    overall_lvl = (
        "Top 5% do Instagram" if overall >= 90 else
        "Acima da média"      if overall >= 65 else
        "Na média"            if overall >= 40 else
        "Abaixo da média"
    )

    return {"metrics": metrics, "overall_percentile": overall, "overall_level": overall_lvl}


# ── Detecção de tendências ────────────────────────────────────────

def detect_trends(posts_30: list, posts_prev_30: list) -> list[dict]:
    """Detecta tendências nas principais métricas vs período anterior."""
    cur  = _scored(posts_30)
    prev = _scored(posts_prev_30)

    def _chg(getter):
        c = _avg(getter(p) for p in cur)
        p = _avg(getter(p) for p in prev)
        pct = round((c - p) / max(p, 1) * 100, 1) if p else 0
        return round(c, 1), round(p, 1), pct

    specs = [
        ("reach",    "Alcance",       "📡", lambda p: p.ig_reach or 0),
        ("likes",    "Curtidas",      "❤️",  lambda p: p.ig_likes or 0),
        ("saves",    "Salvamentos",   "🔖", lambda p: p.ig_saves or 0),
        ("comments", "Comentários",   "💬", lambda p: p.ig_comments or 0),
        ("views",    "Visualizações", "▶️",  lambda p: p.ig_views or 0),
    ]

    _tips = {
        "reach":    (" — ótimo crescimento orgânico!" if True else "", " — revise horários e frequência"),
        "likes":    (" — conteúdo ressoando com a audiência",          " — melhore apelo visual e hook"),
        "saves":    (" — conteúdo de alto valor!",                     " — crie mais conteúdo educativo"),
        "comments": (" — engajamento em alta",                         " — adicione CTAs de pergunta"),
        "views":    (" — ótima distribuição pelo algoritmo",           " — invista em Reels e hooks visuais"),
    }

    trends = []
    for key, label, icon, getter in specs:
        c_val, p_val, pct = _chg(getter)
        direction = "up" if pct > 5 else "down" if pct < -5 else "stable"
        up_tip, down_tip = _tips.get(key, ("", ""))
        if direction == "up":
            insight = f"+{pct}% vs período anterior{up_tip}"
        elif direction == "down":
            insight = f"{pct}% vs período anterior{down_tip}"
        else:
            insight = "Estável nos últimos 60 dias"

        trends.append({
            "metric": key, "label": label, "icon": icon,
            "current_avg": c_val, "prev_avg": p_val,
            "change_pct": pct, "direction": direction, "insight": insight,
        })

    return sorted(trends, key=lambda t: abs(t["change_pct"]), reverse=True)


# ── Resumo executivo ──────────────────────────────────────────────

def executive_summary(posts_30: list, posts_prev_30: list) -> dict:
    """Agrega score, KPIs, tendências, benchmark e previsão em um único dict."""
    from .analytics import post_score as _post_score, type_performance, period_comparison

    cur_scored = _scored(posts_30)
    comp  = period_comparison(posts_30, posts_prev_30)
    types = type_performance(posts_30)

    return {
        "growth_score": growth_score(posts_30, posts_prev_30),
        "kpis": {
            "posts_published":   len([p for p in posts_30 if p.status == "posted"]),
            "total_reach":       comp["current"]["reach"],
            "total_likes":       comp["current"]["likes"],
            "total_saves":       comp["current"]["saves"],
            "avg_post_score":    round(_avg(_post_score(p) for p in cur_scored), 2),
            "reach_delta_pct":   comp["delta"].get("reach", 0),
            "likes_delta_pct":   comp["delta"].get("likes", 0),
            "saves_delta_pct":   comp["delta"].get("saves", 0),
        },
        "best_format": types[0]["label"] if types else "—",
        "trends":      detect_trends(posts_30, posts_prev_30),
        "prediction":  growth_prediction(posts_30),
        "benchmark":   benchmark_data(posts_30),
    }
