"""
Postay — Recommendations Blueprint
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user

from .models import PostQueue

recommendations_bp = Blueprint("recommendations", __name__)


def _history(days=90):
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return PostQueue.query.filter(
        PostQueue.client_id == current_user.id,
        PostQueue.status == "posted",
        PostQueue.posted_at >= cutoff,
    ).order_by(PostQueue.posted_at.desc()).all()


def _all_posted(limit=300):
    return PostQueue.query.filter_by(
        client_id=current_user.id, status="posted"
    ).order_by(PostQueue.posted_at.desc()).limit(limit).all()


@recommendations_bp.route("/recommendations")
@login_required
def index():
    from .recommendations import (
        recommend_schedule, detect_patterns,
        suggest_hashtags, suggest_cta, client_profile,
    )

    posts = _history(90)
    all_posts = _all_posted()

    return render_template(
        "recommendations.html",
        schedule=recommend_schedule(posts),
        patterns=detect_patterns(posts),
        hashtags=suggest_hashtags(posts, n=15),
        ctas=suggest_cta(posts),
        profile=client_profile(all_posts),
        posts_count=len(posts),
    )


@recommendations_bp.route("/api/recommendations/predict")
@login_required
def api_predict():
    from .recommendations import predict_score
    hour = request.args.get("hour", 12, type=int)
    weekday = request.args.get("weekday", 1, type=int)
    post_type = request.args.get("type", "photo")
    posts = _history(90)
    score = predict_score(posts, hour, weekday, post_type)
    return jsonify({"predicted_score": score, "hour": hour, "weekday": weekday, "type": post_type})


@recommendations_bp.route("/api/recommendations/hashtags")
@login_required
def api_hashtags():
    from .recommendations import suggest_hashtags
    return jsonify(suggest_hashtags(_history(90), n=20))


@recommendations_bp.route("/api/recommendations/cta")
@login_required
def api_cta():
    from .recommendations import suggest_cta
    return jsonify(suggest_cta(_history(90)))


@recommendations_bp.route("/api/recommendations/compare")
@login_required
def api_compare():
    from .recommendations import compare_posts_smart
    id_a = request.args.get("a", type=int)
    id_b = request.args.get("b", type=int)
    if not id_a or not id_b:
        return jsonify({"error": "Parâmetros 'a' e 'b' obrigatórios"}), 400
    post_a = PostQueue.query.filter_by(id=id_a, client_id=current_user.id).first_or_404()
    post_b = PostQueue.query.filter_by(id=id_b, client_id=current_user.id).first_or_404()
    return jsonify(compare_posts_smart(post_a, post_b, _all_posted()))
