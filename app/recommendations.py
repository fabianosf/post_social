"""
Postay Recommendations Engine — sugestões inteligentes baseadas em histórico.
Funções puras: sem Flask, sem banco, sem efeitos colaterais.
"""

import re
from collections import defaultdict
from datetime import timezone

from .analytics import post_score, best_time_analysis, type_performance, BRT

_DAY_NAMES_FULL = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

_DEFAULT_CTAS = [
    "Comenta aqui embaixo o que você achou! 👇",
    "Salva esse post para não esquecer! 💾",
    "Compartilha com quem precisa ver isso 📤",
    "Me conta nos comentários sua opinião 💬",
    "Segue o perfil para mais conteúdo assim ➡️",
    "Marca um amigo que precisa ver isso 👥",
]

_TYPE_LABELS = {"photo": "Fotos", "album": "Carrosséis", "reels": "Reels", "story": "Stories"}


def predict_score(posts: list, hour: int, weekday: int, post_type: str) -> float:
    """
    Prediz o score esperado para um post dado horário, dia e tipo.
    Média ponderada: hora (35%), dia (25%), tipo (25%), base global (15%).
    """
    scored = [p for p in posts if p.instagram_media_id and (p.ig_reach or 0) > 0]
    if not scored:
        return 0.0

    all_scores = [post_score(p) for p in scored]
    global_avg = sum(all_scores) / len(all_scores)
    if global_avg == 0:
        return 0.0

    hour_data: dict[int, list] = defaultdict(list)
    day_data: dict[int, list] = defaultdict(list)
    type_data: dict[str, list] = defaultdict(list)

    for p in scored:
        s = post_score(p)
        type_data[p.post_type].append(s)
        if p.posted_at:
            brt = p.posted_at.replace(tzinfo=timezone.utc).astimezone(BRT)
            hour_data[brt.hour].append(s)
            day_data[brt.weekday()].append(s)

    def _avg(lst): return sum(lst) / len(lst) if lst else global_avg
    def _factor(lookup, key): return _avg(lookup.get(key, [])) / global_avg if global_avg else 1.0

    predicted = global_avg * (
        0.35 * _factor(hour_data, hour)
        + 0.25 * _factor(day_data, weekday)
        + 0.25 * _factor(type_data, post_type)
        + 0.15
    )
    return round(min(100.0, predicted), 2)


def recommend_schedule(posts: list) -> list[dict]:
    """
    Retorna top 3 combinações hora × dia com maior score previsto.
    """
    if not posts:
        return []

    bt = best_time_analysis(posts)
    types = type_performance(posts)
    best_type = types[0]["type"] if types else "photo"

    best_hours = [h for h, _ in bt["best_hours"]] or [9, 17, 12]
    best_days = [d for d, _ in bt["best_weekdays"]] or [1, 3, 5]

    seen: set = set()
    candidates = []
    for hour in best_hours:
        for day in best_days:
            if (hour, day) in seen:
                continue
            seen.add((hour, day))
            score = predict_score(posts, hour, day, best_type)
            candidates.append({
                "hour": hour,
                "weekday": day,
                "day_name": _DAY_NAMES_FULL[day],
                "time_str": f"{hour:02d}:00",
                "predicted_score": score,
                "post_type": best_type,
                "type_label": _TYPE_LABELS.get(best_type, best_type),
            })

    candidates.sort(key=lambda x: -x["predicted_score"])
    return candidates[:3]


def detect_patterns(posts: list) -> dict:
    """
    Detecta padrões no histórico: janelas douradas, zonas mortas, viés de formato.
    """
    scored = [p for p in posts if p.instagram_media_id and (p.ig_reach or 0) > 0]
    if not scored:
        return {"golden_windows": [], "dead_zones": [], "format_bias": None, "consistency": "baixa"}

    all_scores = [post_score(p) for p in scored]
    avg = sum(all_scores) / len(all_scores) if all_scores else 0

    hour_data: dict[int, list] = defaultdict(list)
    for p in scored:
        if p.posted_at:
            brt = p.posted_at.replace(tzinfo=timezone.utc).astimezone(BRT)
            hour_data[brt.hour].append(post_score(p))

    golden, dead = [], []
    for hour, hscores in hour_data.items():
        if len(hscores) < 2:
            continue
        h_avg = sum(hscores) / len(hscores)
        if avg > 0 and h_avg >= avg * 1.5:
            golden.append({"hour": hour, "avg_score": round(h_avg, 2), "count": len(hscores)})
        elif avg > 0 and h_avg <= avg * 0.5:
            dead.append({"hour": hour, "avg_score": round(h_avg, 2), "count": len(hscores)})

    golden.sort(key=lambda x: -x["avg_score"])
    dead.sort(key=lambda x: x["avg_score"])

    # Viés de formato
    type_counts: dict[str, int] = defaultdict(int)
    for p in scored:
        type_counts[p.post_type] += 1
    total = sum(type_counts.values())
    format_bias = None
    if type_counts and total > 0:
        dominant = max(type_counts, key=type_counts.get)
        pct = type_counts[dominant] / total * 100
        if pct >= 70:
            format_bias = {
                "type": dominant,
                "label": _TYPE_LABELS.get(dominant, dominant),
                "pct": round(pct),
                "suggestion": f"Você publica {pct:.0f}% {_TYPE_LABELS.get(dominant, dominant)}. Experimente outros formatos.",
            }

    # Consistência: % de semanas com pelo menos 1 post
    consistency = "baixa"
    posted_dates = [p.posted_at for p in posts if p.posted_at]
    if posted_dates:
        weeks = {(d.replace(tzinfo=timezone.utc).astimezone(BRT).isocalendar()[:2]) for d in posted_dates}
        span_weeks = max(1, (max(posted_dates) - min(posted_dates)).days // 7 + 1)
        rate = len(weeks) / span_weeks
        if rate >= 0.8:
            consistency = "alta"
        elif rate >= 0.5:
            consistency = "média"

    return {
        "golden_windows": golden[:3],
        "dead_zones": dead[:3],
        "format_bias": format_bias,
        "consistency": consistency,
    }


def suggest_hashtags(posts: list, n: int = 10) -> list[dict]:
    """
    Ranqueia hashtags dos posts por frequência × score médio.
    """
    tag_data: dict[str, list] = defaultdict(list)
    _re = re.compile(r"#(\w+)", re.UNICODE)

    for p in posts:
        if not p.instagram_media_id:
            continue
        s = post_score(p)
        text = (p.hashtags or "") + " " + (p.caption or "")
        for tag in _re.findall(text.lower()):
            tag_data[tag].append(s)

    result = []
    for tag, scores in tag_data.items():
        avg = sum(scores) / len(scores)
        result.append({
            "hashtag": f"#{tag}",
            "freq": len(scores),
            "avg_score": round(avg, 2),
            "rank": round(len(scores) * avg, 2),
        })

    result.sort(key=lambda x: -x["rank"])
    return result[:n]


def suggest_cta(posts: list) -> list[str]:
    """
    Extrai CTAs dos posts de alto desempenho, completa com defaults.
    """
    scored = [(p, post_score(p)) for p in posts if p.instagram_media_id]
    if not scored:
        return _DEFAULT_CTAS[:4]

    avg = sum(s for _, s in scored) / len(scored)
    top_posts = [p for p, s in scored if s >= avg * 1.2]

    extracted = []
    pattern = re.compile(
        r"(?:[Cc]omenta|[Ss]alva|[Cc]ompartilha|[Ss]egue|[Cc]lica|[Mm]arca|[Dd]eixa|[Mm]e conta)\w*[^\.!?\n]*[\.!?]"
        r"|(?:[Qq]ual|[Vv]ocê|[Ee] você)[^\.!?\n]*\?",
        re.UNICODE,
    )
    for p in top_posts[:10]:
        text = (p.caption or "") + " " + (p.hashtags or "")
        for m in pattern.finditer(text):
            phrase = m.group(0).strip()
            if 10 < len(phrase) < 120 and phrase not in extracted:
                extracted.append(phrase)

    result = extracted[:4]
    for cta in _DEFAULT_CTAS:
        if len(result) >= 6:
            break
        if cta not in result:
            result.append(cta)
    return result[:6]


def client_profile(posts: list) -> dict:
    """
    Caracteriza o perfil de postagem do cliente.
    """
    posted = [p for p in posts if p.status == "posted"]
    total = len(posted)
    if total == 0:
        return {"level": "iniciante", "posts_total": 0, "frequency": "indefinida",
                "dominant_type_label": "—", "preferred_hour": None, "avg_score": 0,
                "freq_per_week": 0, "dominant_type": "photo"}

    dates = sorted([p.posted_at for p in posted if p.posted_at])
    freq_per_week = 0.0
    if len(dates) >= 2:
        span_days = max(1, (dates[-1] - dates[0]).days)
        freq_per_week = total / max(1, span_days / 7)

    if freq_per_week >= 5:
        frequency = "diária"
    elif freq_per_week >= 3:
        frequency = "alta (3-5x/semana)"
    elif freq_per_week >= 1:
        frequency = "regular (1-2x/semana)"
    elif freq_per_week > 0:
        frequency = "baixa"
    else:
        frequency = "indefinida"

    scored_posts = [p for p in posted if p.instagram_media_id]
    avg_score = sum(post_score(p) for p in scored_posts) / len(scored_posts) if scored_posts else 0

    if total >= 50 and avg_score >= 8:
        level = "expert"
    elif total >= 20 and avg_score >= 4:
        level = "avançado"
    elif total >= 5:
        level = "intermediário"
    else:
        level = "iniciante"

    type_counts: dict[str, int] = defaultdict(int)
    hour_counts: dict[int, int] = defaultdict(int)
    for p in posted:
        type_counts[p.post_type] += 1
        if p.posted_at:
            brt = p.posted_at.replace(tzinfo=timezone.utc).astimezone(BRT)
            hour_counts[brt.hour] += 1

    dominant_type = max(type_counts, key=type_counts.get) if type_counts else "photo"
    preferred_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

    return {
        "level": level,
        "posts_total": total,
        "frequency": frequency,
        "freq_per_week": round(freq_per_week, 1),
        "dominant_type": dominant_type,
        "dominant_type_label": _TYPE_LABELS.get(dominant_type, dominant_type),
        "preferred_hour": preferred_hour,
        "avg_score": round(avg_score, 2),
    }


def compare_posts_smart(post_a, post_b, all_posts: list) -> dict:
    """
    Compara dois posts com contexto percentílico do histórico completo.
    """
    all_scores = sorted(post_score(p) for p in all_posts if p.instagram_media_id)

    def _percentile(s):
        if not all_scores:
            return 0
        return round(sum(1 for x in all_scores if x < s) / len(all_scores) * 100)

    sa, sb = post_score(post_a), post_score(post_b)

    metrics = {
        "ig_likes": "Curtidas",
        "ig_comments": "Comentários",
        "ig_saves": "Salvamentos",
        "ig_views": "Visualizações",
        "ig_reach": "Alcance",
    }
    breakdown = {}
    for attr, label in metrics.items():
        va = getattr(post_a, attr) or 0
        vb = getattr(post_b, attr) or 0
        winner = "a" if va > vb else ("b" if vb > va else "tie")
        diff_pct = round((va - vb) / max(vb, 1) * 100, 1) if vb else (100.0 if va else 0.0)
        breakdown[attr] = {"label": label, "a": va, "b": vb, "winner": winner, "diff_pct": diff_pct}

    diff = abs(sa - sb)
    winner_post = post_a if sa >= sb else post_b
    wlabel = _TYPE_LABELS.get(winner_post.post_type, winner_post.post_type)
    winner_letter = "A" if sa >= sb else "B"
    if diff < 0.5:
        verdict = "Performance muito similar entre os dois posts."
    elif diff < 2:
        verdict = f"Post {winner_letter} ({wlabel}) teve performance {round(diff / max(sa, sb) * 100)}% superior."
    else:
        verdict = f"Post {winner_letter} ({wlabel}) se destacou significativamente (score {max(sa,sb):.1f} vs {min(sa,sb):.1f})."

    return {
        "score_a": sa,
        "score_b": sb,
        "winner": "a" if sa > sb else ("b" if sb > sa else "tie"),
        "percentile_a": _percentile(sa),
        "percentile_b": _percentile(sb),
        "breakdown": breakdown,
        "verdict": verdict,
    }
