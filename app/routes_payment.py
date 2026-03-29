"""
Rotas de pagamento PIX — Upgrade para plano Pro.
"""

import os
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required, current_user

from .models import db, Client

payment_bp = Blueprint("payment", __name__, url_prefix="/pagamento")

# Configurações PIX
PIX_KEY = "fabiano.freitas@gmail.com"
PIX_MERCHANT_NAME = "PostSocial"
PIX_MERCHANT_CITY = "SaoPaulo"
PRO_PRICE = 49.90


@payment_bp.route("/")
@login_required
def index():
    """Página de pagamento PIX para upgrade Pro."""
    if current_user.plan == "pro":
        flash("Você já é Pro!", "info")
        return redirect(url_for("dashboard.index"))

    from modules.pix import generate_pix_qrcode_base64, generate_pix_payload

    txid = f"PS{current_user.id}{datetime.now().strftime('%m%y')}"

    qr_base64 = generate_pix_qrcode_base64(
        pix_key=PIX_KEY,
        merchant_name=PIX_MERCHANT_NAME,
        merchant_city=PIX_MERCHANT_CITY,
        amount=PRO_PRICE,
        txid=txid,
        description="PostSocial Pro",
    )

    pix_code = generate_pix_payload(
        pix_key=PIX_KEY,
        merchant_name=PIX_MERCHANT_NAME,
        merchant_city=PIX_MERCHANT_CITY,
        amount=PRO_PRICE,
        txid=txid,
        description="PostSocial Pro",
    )

    brand = {
        "name": current_user.brand_name or "PostSocial",
        "color": current_user.brand_color or "#7c5cff",
    }

    return render_template(
        "payment.html",
        qr_base64=qr_base64,
        pix_code=pix_code,
        pix_key=PIX_KEY,
        price=PRO_PRICE,
        txid=txid,
        brand=brand,
    )


@payment_bp.route("/qrcode.png")
@login_required
def qrcode_image():
    """Retorna a imagem do QR Code PIX como PNG."""
    from modules.pix import generate_pix_qrcode_bytes

    txid = f"PS{current_user.id}{datetime.now().strftime('%m%y')}"

    img_bytes = generate_pix_qrcode_bytes(
        pix_key=PIX_KEY,
        merchant_name=PIX_MERCHANT_NAME,
        merchant_city=PIX_MERCHANT_CITY,
        amount=PRO_PRICE,
        txid=txid,
        description="PostSocial Pro",
    )

    return Response(img_bytes, mimetype="image/png")


@payment_bp.route("/confirmar", methods=["POST"])
@login_required
def confirm_payment():
    """Cliente informa que fez o pagamento — fica pendente até admin aprovar."""
    if current_user.plan == "pro":
        flash("Você já é Pro!", "info")
        return redirect(url_for("dashboard.index"))

    current_user.plan = "pending_pro"
    db.session.commit()
    flash("Pagamento informado! Seu plano será ativado assim que confirmarmos o PIX.", "success")
    return redirect(url_for("dashboard.index"))
