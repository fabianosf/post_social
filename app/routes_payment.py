"""
Rotas de pagamento — Mercado Pago (checkout) + PIX manual como fallback.
"""

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

_BRT = ZoneInfo("America/Sao_Paulo")

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import login_required, current_user

from .models import db, Client

payment_bp = Blueprint("payment", __name__, url_prefix="/pagamento")
logger = logging.getLogger(__name__)

# Configurações via .env
MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "").strip()
MP_WEBHOOK_SECRET = os.environ.get("MP_WEBHOOK_SECRET", "").strip()
PIX_KEY = os.environ.get("PIX_KEY", "").strip()
PIX_MERCHANT_NAME = os.environ.get("PIX_MERCHANT_NAME", "Postay").strip() or "Postay"
PIX_MERCHANT_CITY = os.environ.get("PIX_MERCHANT_CITY", "SaoPaulo").strip() or "SaoPaulo"
PRO_PRICE = float(os.environ.get("PRO_PRICE", "99.90"))
AGENCY_PRICE = float(os.environ.get("AGENCY_PRICE", "249.00"))
APP_BASE_URL = (
    os.environ.get("APP_BASE_URL", "").strip()
    or os.environ.get("PUBLIC_BASE_URL", "https://postay.com.br").strip()
).rstrip("/")


def _parse_external_reference(ext_ref: str) -> tuple[int | None, str]:
    """Formato: '42:pro', '42:agency' ou legado '42' → pro."""
    ref = (ext_ref or "").strip()
    if ":" in ref:
        cid, plan = ref.split(":", 1)
        if cid.isdigit() and plan in ("pro", "agency"):
            return int(cid), plan
    if ref.isdigit():
        return int(ref), "pro"
    return None, "pro"


def _activate_plan(client: Client, plan: str, payment_id: str, days: int = 30) -> bool:
    """Ativa ou renova plano pago. Retorna True se alterou o banco."""
    plan = plan if plan in ("pro", "agency") else "pro"
    now = datetime.now(timezone.utc)
    pid = str(payment_id)
    if client.mp_payment_id == pid and client.plan == plan:
        return False
    client.plan = plan
    client.mp_payment_id = pid
    base = client.plan_expires_at
    if base and base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    if base and base > now:
        client.plan_expires_at = base + timedelta(days=days)
    else:
        client.plan_expires_at = now + timedelta(days=days)
    db.session.commit()
    return True


def _activate_pro(client: Client, payment_id: str, days: int = 30) -> bool:
    return _activate_plan(client, "pro", payment_id, days)


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
    target = (request.args.get("plan") or "pro").lower()
    if target not in ("pro", "agency"):
        target = "pro"
    is_trial = (current_user.plan_expires_at is not None and not current_user.mp_subscription_id)
    if current_user.plan == target and not current_user.is_admin and not is_trial:
        flash(f"Você já tem o plano {target.upper()}!", "info")
        return redirect(url_for("dashboard.index"))
    if current_user.plan == "agency" and target == "pro" and not current_user.is_admin:
        flash("Você já está no plano Agency.", "info")
        return redirect(url_for("dashboard.index"))

    price = AGENCY_PRICE if target == "agency" else PRO_PRICE
    plan_label = "Agency" if target == "agency" else "Pro"

    mp_available = bool(MP_ACCESS_TOKEN)
    pix_available = bool(PIX_KEY)

    brand = {
        "name": current_user.brand_name or "Postay",
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
                            "title": f"Postay {plan_label} — Assinatura Mensal",
                            "quantity": 1,
                            "unit_price": price,
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
                    "external_reference": f"{current_user.id}:{target}",
                    "notification_url": f"{APP_BASE_URL}/pagamento/webhook",
                    "statement_descriptor": "POSTSOCIAL",
                }
                result = sdk.preference().create(pref_data)
                pref = result.get("response", {})
                mp_checkout_url = pref.get("init_point") or pref.get("sandbox_init_point")
            except Exception as exc:
                logger.warning("MP preference create failed: %s", exc)
                mp_available = False

    # PIX fallback
    qr_base64 = None
    pix_code = None
    txid = None
    if pix_available:
        try:
            from modules.pix import generate_pix_qrcode_base64, generate_pix_payload
            txid = f"PS{current_user.id}{target[0].upper()}{datetime.now(_BRT).strftime('%m%y')}"
            qr_base64 = generate_pix_qrcode_base64(
                pix_key=PIX_KEY,
                merchant_name=PIX_MERCHANT_NAME,
                merchant_city=PIX_MERCHANT_CITY,
                amount=price,
                txid=txid,
                description=f"Postay {plan_label}",
            )
            pix_code = generate_pix_payload(
                pix_key=PIX_KEY,
                merchant_name=PIX_MERCHANT_NAME,
                merchant_city=PIX_MERCHANT_CITY,
                amount=price,
                txid=txid,
                description=f"Postay {plan_label}",
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
        price=price,
        target_plan=target,
        plan_label=plan_label,
        txid=txid,
        brand=brand,
    )


# ── Webhook Mercado Pago ──────────────────────────

@payment_bp.route("/webhook", methods=["GET", "POST"])
def mp_webhook():
    """Recebe notificações do Mercado Pago e ativa plano Pro automaticamente."""
    if request.method == "GET":
        return jsonify({"status": "ok"}), 200

    body = request.get_json(silent=True) or {}
    resource_id = str((body.get("data") or {}).get("id") or request.args.get("id") or "").strip()
    topic = (body.get("type") or body.get("action") or request.args.get("topic") or "").lower()

    if MP_WEBHOOK_SECRET and resource_id:
        x_signature = request.headers.get("x-signature", "")
        x_request_id = request.headers.get("x-request-id", "")
        sig_parts = dict(p.split("=", 1) for p in x_signature.split(",") if "=" in p)
        ts = sig_parts.get("ts", "")
        v1 = sig_parts.get("v1", "")
        manifest = f"id:{resource_id};request-id:{x_request_id};ts:{ts};"
        expected = hmac.new(
            MP_WEBHOOK_SECRET.encode(),
            manifest.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not v1 or not hmac.compare_digest(v1, expected):
            logger.warning("MP webhook: assinatura inválida id=%s", resource_id)
            return jsonify({"error": "invalid signature"}), 401

    if "payment" not in topic or not resource_id:
        return jsonify({"status": "ok"}), 200

    sdk = _mp_sdk()
    if not sdk:
        return jsonify({"status": "ok"}), 200

    try:
        result = sdk.payment().get(resource_id)
        payment = result.get("response", {})
        status = payment.get("status")
        ext_ref = str(payment.get("external_reference", "") or "")
        client_id, plan = _parse_external_reference(ext_ref)

        if status == "approved" and client_id:
            client = db.session.get(Client, client_id)
            if client:
                _activate_plan(client, plan, resource_id)
    except Exception as exc:
        logger.error("MP webhook payment %s: %s", resource_id, exc)

    return jsonify({"status": "ok"}), 200


# ── Retorno do checkout ───────────────────────────

@payment_bp.route("/sucesso")
@login_required
def success():
    payment_id = request.args.get("payment_id") or request.args.get("collection_id")
    status = (request.args.get("status") or request.args.get("collection_status") or "").lower()
    activated = False
    plan_label = "PRO"

    if status == "approved" and payment_id:
        sdk = _mp_sdk()
        if sdk:
            try:
                result = sdk.payment().get(payment_id)
                payment = result.get("response", {})
                mp_status = payment.get("status")
                ext_ref = str(payment.get("external_reference", "") or "")
                client_id, plan = _parse_external_reference(ext_ref)
                plan_label = plan.upper()
                if mp_status == "approved" and client_id == current_user.id:
                    _activate_plan(current_user, plan, str(payment_id))
                    activated = True
            except Exception as exc:
                logger.warning("MP success callback verify failed: %s", exc)
        else:
            activated = True  # sem SDK, confia no retorno do MP

    from datetime import timezone as _tz
    expires_str = None
    if current_user.plan_expires_at:
        from zoneinfo import ZoneInfo
        brt = current_user.plan_expires_at.replace(tzinfo=_tz.utc).astimezone(ZoneInfo("America/Sao_Paulo"))
        expires_str = brt.strftime("%d/%m/%Y")

    return render_template(
        "payment_success.html",
        activated=activated,
        plan_label=plan_label,
        expires_str=expires_str,
    )


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
    target = (request.form.get("target_plan") or "pro").lower()
    if target not in ("pro", "agency"):
        target = "pro"
    if current_user.plan == target:
        flash(f"Você já tem o plano {target.upper()}!", "info")
        return redirect(url_for("dashboard.index"))

    current_user.plan = "pending_agency" if target == "agency" else "pending_pro"
    db.session.commit()
    flash("Pagamento informado! Seu plano será ativado assim que confirmarmos o PIX.", "success")
    return redirect(url_for("dashboard.index"))


@payment_bp.route("/qrcode.png")
@login_required
def qrcode_image():
    if not PIX_KEY:
        return Response("PIX não configurado", status=503)
    from modules.pix import generate_pix_qrcode_bytes
    target = (request.args.get("plan") or "pro").lower()
    price = AGENCY_PRICE if target == "agency" else PRO_PRICE
    txid = f"PS{current_user.id}{target[0].upper()}{datetime.now(_BRT).strftime('%m%y')}"
    img_bytes = generate_pix_qrcode_bytes(
        pix_key=PIX_KEY,
        merchant_name=PIX_MERCHANT_NAME,
        merchant_city=PIX_MERCHANT_CITY,
        amount=price,
        txid=txid,
        description="Postay",
    )
    return Response(img_bytes, mimetype="image/png")
