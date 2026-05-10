"""
Rotas de configuração: templates, watermark, white label, Telegram.
"""

import os
import re

from flask import flash, redirect, request, url_for, jsonify, current_app
from flask_login import login_required, current_user

from ..models import db, CaptionTemplate
from . import dashboard_bp


@dashboard_bp.route("/templates/save", methods=["POST"])
@login_required
def save_template():
    name = request.form.get("template_name", "").strip()
    content = request.form.get("template_content", "").strip()
    hashtags = request.form.get("template_hashtags", "").strip()

    if not name or not content:
        flash("Preencha nome e conteúdo do template.", "error")
        return redirect(url_for("dashboard.index"))

    template = CaptionTemplate(
        client_id=current_user.id,
        name=name,
        content=content,
        hashtags=hashtags,
    )
    db.session.add(template)
    db.session.commit()
    flash(f"Template '{name}' salvo!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def delete_template(template_id):
    template = CaptionTemplate.query.filter_by(id=template_id, client_id=current_user.id).first()
    if template:
        db.session.delete(template)
        db.session.commit()
        flash("Template removido.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/watermark", methods=["POST"])
@login_required
def update_watermark():
    file = request.files.get("watermark_file")
    current_user.watermark_enabled = request.form.get("watermark_enabled") == "on"
    current_user.watermark_position = request.form.get("watermark_position", "bottom-right")
    try:
        current_user.watermark_opacity = max(0, min(100, int(request.form.get("watermark_opacity", 80))))
    except (ValueError, TypeError):
        current_user.watermark_opacity = 80

    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[1].lower()
        if ext in {"png", "jpg", "jpeg", "webp"}:
            wm_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(current_user.id), "watermarks")
            os.makedirs(wm_dir, exist_ok=True)
            wm_path = os.path.join(wm_dir, f"watermark.{ext}")
            file.save(wm_path)
            current_user.watermark_path = wm_path

    db.session.commit()
    flash("Configuração de watermark atualizada!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/whitelabel", methods=["POST"])
@login_required
def update_whitelabel():
    if not current_user.is_pro():
        flash("White Label é um recurso exclusivo do Plano Pro. Faça upgrade para usar!", "error")
        return redirect(url_for("dashboard.index"))

    brand_name = request.form.get("brand_name", "").strip()
    brand_color = request.form.get("brand_color", "").strip()

    if brand_name:
        current_user.brand_name = brand_name
    if brand_color and re.match(r'^#[0-9a-fA-F]{6}$', brand_color):
        current_user.brand_color = brand_color

    db.session.commit()
    flash("Configuração de marca atualizada!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/api/telegram-config", methods=["POST"])
@login_required
def save_telegram_config():
    data = request.get_json()
    current_user.telegram_bot_token = data.get("bot_token", "").strip() or None
    current_user.telegram_chat_id = data.get("chat_id", "").strip() or None
    db.session.commit()
    if current_user.telegram_bot_token and current_user.telegram_chat_id:
        from modules.telegram_notify import send_telegram
        ok = send_telegram(current_user.telegram_bot_token, current_user.telegram_chat_id,
                           "✅ <b>Postay conectado!</b>\nVocê receberá alertas aqui.")
        return jsonify({"ok": True, "tested": ok})
    return jsonify({"ok": True, "tested": False})
