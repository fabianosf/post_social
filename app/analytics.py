"""
Postay Analytics Engine — computa insights a partir de PostQueue.
Funções puras: sem Flask, sem banco, sem efeitos colaterais.
"""

from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BRT = ZoneInfo("America/Sao_Paulo")

# ── Score por post ────────────────────────────────────────────────

def post_score(post) -> float:
    """
    Score de engajamento 0-100.
    Pesos: saves(5) > comments(3) > likes(1) > views(0.1)
    Normalizado pelo alcance.
    """
    reach = max(post.ig_reach or 0, 1)
    likes = post.ig_likes or 0
    comments = post.ig_comments or 0
    saves = post.ig_saves or 0
    views = post.ig_views or 0

    weighted = likes * 1.0 + comments * 3.0 + saves * 5.0 + views * 0.1
    rate = (weighted / reach) * 100
    return min(100.0, round(rate, 2))


def score_label(score: float) -> str:
    if score >= 15:
        return "Viral"
    if score >= 8:
        return "Excelente"
    if score >= 4:
        return "Bom"
    if score >= 1:
        return "Regular"
    return "Baixo"


def score_color(score: float) -> str:
    if score >= 15:
        return "#f59e0b"   # gold
    if score >= 8:
        return "#4ade80"   # green
    if score >= 4:
        return "#60a5fa"   # blue
    if score >= 1:
        return "#a78bfa"   # purple
    return "#6b7280"       # gray


# ── Ranking de posts ──────────────────────────────────────────────

def rank_posts(posts: list) -> list[dict]:
    """Retorna lista ordenada por score com rank, score, label e cor."""
    scored = []
    for p in posts:
        if not p.instagram_media_id:
            continue
        s = post_score(p)
        scored.append({
            "post": p,
            "score": s,
            "label": score_label(s),
            "color": score_color(s),
        })
    scored.sort(key=lambda x: -x["score"])
    for i, item in enumerate(scored):
        item["rank"] = i + 1
    return scored


# ── Best time to post ─────────────────────────────────────────────

def best_time_analysis(posts: list) -> dict:
    """
    Analisa posts publicados e retorna melhores horas e dias.
    Retorna horas em BRT.
    """
    hour_scores: dict[int, list[float]] = defaultdict(list)
    day_scores: dict[int, list[float]] = defaultdict(list)
    # Heatmap: bloco de 4h × dia da semana
    heatmap: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    for p in posts:
        if not p.posted_at:
            continue
        s = post_score(p)
        brt = p.posted_at.replace(tzinfo=timezone.utc).astimezone(BRT)
        hour = brt.hour
        block = hour // 4      # 0-5 blocos de 4h: 0-3, 4-7, 8-11, 12-15, 16-19, 20-23
        weekday = brt.weekday()  # 0=Seg, 6=Dom

        hour_scores[hour].append(s)
        day_scores[weekday].append(s)
        heatmap[weekday][block].append(s)

    def _avg(lst): return round(sum(lst) / len(lst), 2) if lst else 0.0

    avg_hours = sorted(
        [(h, _avg(v)) for h, v in hour_scores.items()],
        key=lambda x: -x[1]
    )
    avg_days = sorted(
        [(d, _avg(v)) for d, v in day_scores.items()],
        key=lambda x: -x[1]
    )

    # Heatmap: normalizado 0-100 para coloração
    hm_flat = {}
    all_scores = []
    for wd, blocks in heatmap.items():
        for blk, scores in blocks.items():
            avg = _avg(scores)
            hm_flat[(wd, blk)] = avg
            all_scores.append(avg)

    max_score = max(all_scores) if all_scores else 1
    heatmap_norm = {k: round(v / max_score * 100) for k, v in hm_flat.items()}

    return {
        "best_hours": avg_hours[:3],           # top 3 horas
        "worst_hours": avg_hours[-3:],          # piores 3 horas
        "best_weekdays": avg_days[:3],          # top 3 dias
        "worst_weekdays": avg_days[-3:],        # piores 3 dias
        "heatmap": heatmap_norm,                # {(weekday, block): intensity 0-100}
        "total_posts_analyzed": len([p for p in posts if p.posted_at]),
    }


# ── Comparação de períodos ────────────────────────────────────────

def _aggregate(posts: list) -> dict:
    published = [p for p in posts if p.status == "posted"]
    return {
        "count": len(published),
        "likes": sum(p.ig_likes or 0 for p in published),
        "comments": sum(p.ig_comments or 0 for p in published),
        "saves": sum(p.ig_saves or 0 for p in published),
        "views": sum(p.ig_views or 0 for p in published),
        "reach": sum(p.ig_reach or 0 for p in published),
        "failed": len([p for p in posts if p.status == "failed"]),
    }


def _delta_pct(new: int | float, old: int | float) -> float:
    if old == 0:
        return 100.0 if new > 0 else 0.0
    return round((new - old) / old * 100, 1)


def period_comparison(posts_current: list, posts_previous: list) -> dict:
    curr = _aggregate(posts_current)
    prev = _aggregate(posts_previous)
    delta = {k: _delta_pct(curr[k], prev[k]) for k in curr}
    return {"current": curr, "previous": prev, "delta": delta}


# ── Performance por tipo de post ──────────────────────────────────

def type_performance(posts: list) -> list[dict]:
    """Compara score médio por tipo de post."""
    by_type: dict[str, list[float]] = defaultdict(list)
    for p in posts:
        if p.instagram_media_id:
            by_type[p.post_type].append(post_score(p))

    labels = {"photo": "Foto", "album": "Carrossel", "reels": "Reels", "story": "Story"}
    result = []
    for ptype, scores in by_type.items():
        avg = round(sum(scores) / len(scores), 2) if scores else 0
        result.append({
            "type": ptype,
            "label": labels.get(ptype, ptype),
            "avg_score": avg,
            "count": len(scores),
            "label_score": score_label(avg),
            "color": score_color(avg),
        })
    result.sort(key=lambda x: -x["avg_score"])
    return result


# ── Insights automáticos ──────────────────────────────────────────

_DAY_NAMES = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
_BLOCK_LABELS = ["00-04h", "04-08h", "08-12h", "12-16h", "16-20h", "20-24h"]


def generate_insights(posts: list, best_time: dict, comparison: dict, types: list) -> list[dict]:
    """
    Gera insights textuais com ícone, texto e severidade (info/success/warning).
    Retorna lista de dicts: {icon, text, severity}
    """
    insights = []
    delta = comparison.get("delta", {})
    curr = comparison.get("current", {})

    # 1. Melhor horário
    if best_time["best_hours"]:
        h, score = best_time["best_hours"][0]
        insights.append({
            "icon": "⏰",
            "text": f"Poste às {h:02d}h para máximo engajamento (score médio {score:.1f})",
            "severity": "success",
        })

    # 2. Melhor dia
    if best_time["best_weekdays"]:
        wd, score = best_time["best_weekdays"][0]
        insights.append({
            "icon": "📅",
            "text": f"{_DAY_NAMES[wd]} é seu melhor dia (score {score:.1f}). Priorize este dia.",
            "severity": "success",
        })

    # 3. Pior horário (evitar)
    if best_time["worst_hours"] and len(best_time["best_hours"]) >= 1:
        best_h_score = best_time["best_hours"][0][1]
        worst_h, worst_score = best_time["worst_hours"][0]
        if best_h_score > 0 and worst_score < best_h_score * 0.3:
            insights.append({
                "icon": "🚫",
                "text": f"Evite postar às {worst_h:02d}h — engajamento {round((1 - worst_score/best_h_score)*100)}% menor que seu pico.",
                "severity": "warning",
            })

    # 4. Melhor tipo de post
    if types:
        best = types[0]
        if best["count"] >= 2:
            insights.append({
                "icon": "🏆",
                "text": f"{best['label']}s têm o melhor desempenho (score médio {best['avg_score']:.1f} — {best['label_score']}).",
                "severity": "info",
            })
        if len(types) >= 2:
            worst = types[-1]
            if worst["avg_score"] < best["avg_score"] * 0.4 and worst["count"] >= 2:
                insights.append({
                    "icon": "💡",
                    "text": f"{worst['label']}s têm desempenho 60% menor. Considere usar mais {best['label']}s.",
                    "severity": "warning",
                })

    # 5. Crescimento de alcance
    reach_delta = delta.get("reach", 0)
    if reach_delta >= 20:
        insights.append({
            "icon": "📈",
            "text": f"Alcance cresceu {reach_delta:.0f}% em relação ao período anterior. Continue assim!",
            "severity": "success",
        })
    elif reach_delta <= -20:
        insights.append({
            "icon": "📉",
            "text": f"Alcance caiu {abs(reach_delta):.0f}%. Tente variar horários ou formatos.",
            "severity": "warning",
        })

    # 6. Saves (indicador de conteúdo de referência)
    total_saves = curr.get("saves", 0)
    total_posts = curr.get("count", 0)
    if total_posts > 0 and total_saves > 0:
        saves_per_post = total_saves / total_posts
        if saves_per_post >= 5:
            insights.append({
                "icon": "💾",
                "text": f"Média de {saves_per_post:.0f} salvamentos por post — conteúdo de alta qualidade!",
                "severity": "success",
            })

    # 7. Volume de posts
    count_delta = delta.get("count", 0)
    if count_delta >= 30:
        insights.append({
            "icon": "✅",
            "text": f"Você publicou {count_delta:.0f}% mais posts neste período. Consistência gera crescimento.",
            "severity": "success",
        })
    elif count_delta <= -30 and total_posts < 3:
        insights.append({
            "icon": "⚠️",
            "text": "Poucas publicações no período. Tente manter pelo menos 3 posts por semana.",
            "severity": "warning",
        })

    # 8. Alta taxa de falhas
    failed = curr.get("failed", 0)
    if failed >= 3:
        insights.append({
            "icon": "🔧",
            "text": f"{failed} posts falharam neste período. Reconecte sua conta Instagram no painel.",
            "severity": "warning",
        })

    return insights[:6]  # máximo 6 insights por vez


# ── Trend de crescimento ──────────────────────────────────────────

def growth_trend(daily_data: list[dict]) -> dict:
    """
    Recebe lista de {day, count, likes, reach}.
    Retorna tendência linear simples (slope positivo = crescendo).
    """
    n = len(daily_data)
    if n < 2:
        return {"trend": "stable", "slope": 0}

    # Regressão linear simples sobre 'reach'
    values = [d.get("reach", 0) for d in daily_data]
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n

    num = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0

    if slope > 0.5:
        trend = "up"
    elif slope < -0.5:
        trend = "down"
    else:
        trend = "stable"

    return {"trend": trend, "slope": round(slope, 2)}
