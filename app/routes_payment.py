"""
Rotas de pagamento — Mercado Pago (checkout) + PIX manual como fallback.
"""

import hashlib
import hmac
import os
from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import login_required, current_user

from .models import db, Client

payment_bp = Blueprint("payment", __name__, url_prefix="/pagamento")

# Configurações via .env
MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
MP_WEBHOOK_SECRET = os.environ.get("MP_WEBHOOK_SECRET", "")
PIX_KEY = os.environ.get("PIX_KEY", "")
PIX_MERCHANT_NAME = os.environ.get("PIX_MERCHANT_NAME", "PostSocial")
PIX_MERCHANT_CITY = os.environ.get("PIX_MERCHANT_CITY", "SaoPaulo")
PRO_PRICE = float(os.environ.get("PRO_PRICE", "49.90"))
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")


# ── Mercado Pago SDK helper ───────────────────────

def _mp_sdk():
    """Retorna instância do SDK do Mercado Pago, ou None se não configurado."""
    if not MP_ACCESS_TOKEN:
        return None
    try:
        import mercadopago
        sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
        return sdk
    except ImportError:
        return None


# ── Checkout principal ────────────────────────────

@payment_bp.route("/")
@login_required
def index():
    if current_user.is_pro() and not current_user.is_admin:
        flash("Você já tem o plano Pro!", "info")
        return redirect(url_for("dashboard.index"))

    mp_available = bool(MP_ACCESS_TOKEN)
    pix_available = bool(PIX_KEY)

    brand = {
        "name": current_user.brand_name or "PostSocial",
        "color": current_user.brand_color or "#7c5cff",
    }

    # Tentar criar preferência MP
    mp_checkout_url = None
    if mp_available:
        sdk = _mp_sdk()
        if sdk:
            try:
                pref_data = {
                    "items": [
                        {
                            "title": "PostSocial Pro — Assinatura Mensal",
                            "quantity": 1,
                            "unit_price": PRO_PRICE,
                            "currency_id": "BRL",
                        }
                    ],
                    "payer": {"email": current_user.email},
                    "back_urls": {
                        "success": f"{APP_BASE_URL}/pagamento/sucesso",
                        "failure": f"{APP_BASE_URL}/pagamento/falha",
                        "pending": f"{APP_BASE_URL}/pagamento/pendente",
                    },
                    "auto_return": "approved",
                    "external_reference": str(current_user.id),
                    "notification_url": f"{APP_BASE_URL}/pagamento/webhook",
                    "statement_descriptor": "POSTSOCIAL",
                }
                result = sdk.preference().create(pref_data)
                pref = result.get("response", {})
                mp_checkout_url = pref.get("init_point")
            except Exception:
                mp_available = False

    # PIX fallback
    qr_base64 = None
    pix_code = None
    txid = None
    if pix_available:
        try:
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
        except Exception:
            pix_available = False

    return render_template(
        "payment.html",
        mp_checkout_url=mp_checkout_url,
        mp_available=mp_available,
        pix_available=pix_available,
        qr_base64=qr_base64,
        pix_code=pix_code,
        pix_key=PIX_KEY,
        price=PRO_PRICE,
        txid=txid,
        brand=brand,
    )


# ── Webhook Mercado Pago ──────────────────────────

@payment_bp.route("/webhook", methods=["POST"])
def mp_webhook():
    """Recebe notificações do Mercado Pago e ativa plano Pro automaticamente."""
    # Verificar assinatura (se configurado)
    if MP_WEBHOOK_SECRET:
        sig = request.headers.get("x-signature", "")
        ts_header = request.headers.get("x-request-id", "")
        body = request.get_data()
        expected = hmac.new(
            MP_WEBHOOK_SECRET.encode(),
            f"id={ts_header};{body.decode()}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return jsonify({"error": "invalid signature"}), 401

    data = request.get_json(silent=True) or {}
    topic = data.get("type") or request.args.get("topic", "")
    resource_id = (data.get("data", {}) or {}).get("id") or request.args.get("id")

    if topic == "payment" and resource_id:
        sdk = _mp_sdk()
        if sdk:
            try:
                result = sdk.payment().get(resource_id)
                payment = result.get("response", {})
                status = payment.get("status")
                ext_ref = payment.get("external_reference", "")
                client_id = int(ext_ref) if ext_ref and ext_ref.isdigit() else None

                if status == "approved" and client_id:
                    client = db.session.get(Client, client_id)
                    if client and not client.is_pro():
                        client.plan = "pro"
                        client.mp_payment_id = str(resource_id)
                        client.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                        db.session.commit()
            except Exception:
                pass

    return jsonify({"status": "ok"}), 200


# ── Retorno do checkout ───────────────────────────

@payment_bp.route("/sucesso")
@login_required
def success():
    payment_id = request.args.get("payment_id")
    status = request.args.get("status")

    if status == "approved" and payment_id:
        if not current_user.is_pro():
            current_user.plan = "pro"
            current_user.mp_payment_id = str(payment_id)
            current_user.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            db.session.commit()
        flash("🎉 Pagamento aprovado! Plano Pro ativado com sucesso.", "success")
    else:
        flash("Pagamento em processamento. Seu plano será ativado em breve.", "info")

    return redirect(url_for("dashboard.index"))


@payment_bp.route("/pendente")
@login_required
def pending():
    flash("Pagamento pendente. Ativaremos seu plano assim que for confirmado.", "info")
    return redirect(url_for("dashboard.index"))


@payment_bp.route("/falha")
@login_required
def failure():
    flash("Pagamento não aprovado. Tente novamente ou use o PIX.", "error")
    return redirect(url_for("payment.index"))


# ── PIX manual (fallback) ─────────────────────────

@payment_bp.route("/confirmar", methods=["POST"])
@login_required
def confirm_payment():
    if current_user.is_pro():
        flash("Você já é Pro!", "info")
        return redirect(url_for("dashboard.index"))

    current_user.plan = "pending_pro"
    db.session.commit()
    flash("Pagamento informado! Seu plano será ativado assim que confirmarmos o PIX.", "success")
    return redirect(url_for("dashboard.index"))


@payment_bp.route("/qrcode.png")
@login_required
def qrcode_image():
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
