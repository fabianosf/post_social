"""
Postay — Vision Routes (Fase 8)
Endpoints para análise visual de imagens e vídeos.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from . import vision_service
from .models import AIInsight, PostQueue, db

vision_bp = Blueprint("vision", __name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def _ext(filename: str) -> str:
    return os.path.splitext(filename.lower())[1]


def _post_file_path(post: PostQueue) -> str | None:
    upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
    path = os.path.join(upload_folder, post.image_filename)
    return path if os.path.exists(path) else None


# ── GET /api/vision/status ────────────────────────────────────────

@vision_bp.route("/api/vision/status")
@login_required
def api_status():
    return jsonify({
        "available": vision_service.is_vision_available(),
        "provider": os.environ.get("AI_PROVIDER", "openai"),
        "ffmpeg": vision_service.ffmpeg_available(),
    })


# ── POST /api/vision/post/<int:post_id> ───────────────────────────

@vision_bp.route("/api/vision/post/<int:post_id>", methods=["POST"])
@login_required
def api_analyze_post(post_id: int):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first_or_404()

    now = datetime.now(timezone.utc)
    cached = (
        AIInsight.query
        .filter(
            AIInsight.client_id == current_user.id,
            AIInsight.insight_type == "visual_analysis",
            AIInsight.post_id == post_id,
            (AIInsight.expires_at == None) | (AIInsight.expires_at > now),
        )
        .order_by(AIInsight.created_at.desc())
        .first()
    )
    if cached:
        return jsonify({**json.loads(cached.content), "cached": True})

    path = _post_file_path(post)
    if not path:
        return jsonify({"error": "Arquivo não encontrado no servidor"}), 404

    body = request.get_json(silent=True) or {}
    niche = body.get("niche", "geral")

    ext = _ext(post.image_filename)
    if ext in _VIDEO_EXTS:
        result = vision_service.analyze_video(path, niche)
    else:
        result = vision_service.analyze_image(path, niche)

    if result is None:
        return jsonify({"error": "Falha na análise visual"}), 500

    expires = now + timedelta(days=7)
    row = AIInsight(
        client_id=current_user.id,
        post_id=post_id,
        insight_type="visual_analysis",
        content=json.dumps(result, ensure_ascii=False),
        expires_at=expires,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(result)


# ── POST /api/vision/upload ───────────────────────────────────────

@vision_bp.route("/api/vision/upload", methods=["POST"])
@login_required
def api_analyze_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "Arquivo não enviado"}), 400

    ext = _ext(file.filename)
    if ext not in _IMAGE_EXTS and ext not in _VIDEO_EXTS:
        return jsonify({"error": "Formato não suportado. Use JPG, PNG, MP4 ou MOV."}), 400

    niche = request.form.get("niche", "geral")

    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    result = None
    try:
        file.save(tmp_path)
        if ext in _VIDEO_EXTS:
            result = vision_service.analyze_video(tmp_path, niche)
        else:
            result = vision_service.analyze_image(tmp_path, niche)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if result is None:
        return jsonify({"error": "Falha na análise visual"}), 500

    return jsonify(result)
