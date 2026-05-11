"""
Gerenciamento de API keys de IA por usuário.
Keys são criptografadas com Fernet (AES-128-CBC) derivado do SECRET_KEY da app.
"""

import base64
import hashlib

import requests as _req
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from .models import UserAIKey, db

ai_keys_bp = Blueprint("ai_keys", __name__)

PROVIDERS = {
    "openai":      "OpenAI",
    "gemini":      "Google Gemini",
    "groq":        "Groq",
    "claude":      "Anthropic Claude",
    "openrouter":  "OpenRouter",
}

# Endpoints usados apenas para testar validade das chaves
_TEST_URLS = {
    "openai":     ("https://api.openai.com/v1/models",                        lambda k: {"Authorization": f"Bearer {k}"}),
    "groq":       ("https://api.groq.com/openai/v1/models",                   lambda k: {"Authorization": f"Bearer {k}"}),
    "gemini":     (lambda k: f"https://generativelanguage.googleapis.com/v1beta/models?key={k}", lambda k: {}),
    "claude":     ("https://api.anthropic.com/v1/models",                     lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}),
    "openrouter": ("https://openrouter.ai/api/v1/models",                     lambda k: {"Authorization": f"Bearer {k}"}),
}


def _fernet():
    from cryptography.fernet import Fernet
    raw = current_app.config["SECRET_KEY"]
    key = hashlib.sha256(raw.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def _decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def _mask(plain: str) -> str:
    if len(plain) <= 8:
        return "••••••••"
    return plain[:4] + "••••••••" + plain[-4:]


# ── GET /api/ai-keys ─────────────────────────────────────────────────────────

@ai_keys_bp.route("/api/ai-keys")
@login_required
def list_keys():
    rows = UserAIKey.query.filter_by(client_id=current_user.id).all()
    saved = {r.provider: r for r in rows}

    result = []
    for prov, label in PROVIDERS.items():
        row = saved.get(prov)
        masked = _mask(_decrypt(row.enc_key)) if row else None
        result.append({
            "provider":          prov,
            "label":             label,
            "has_key":           row is not None,
            "masked_key":        masked,
            "is_active":         row.is_active if row else False,
            "is_default":        row.is_default if row else False,
            "last_validated_at": row.last_validated_at.isoformat() if row and row.last_validated_at else None,
        })
    return jsonify(result)


# ── POST /api/ai-keys ────────────────────────────────────────────────────────

@ai_keys_bp.route("/api/ai-keys", methods=["POST"])
@login_required
def save_key():
    data = request.get_json(silent=True) or {}
    provider = data.get("provider", "").strip()
    api_key  = data.get("api_key", "").strip()

    if provider not in PROVIDERS:
        return jsonify({"error": "Provider inválido"}), 400
    if not api_key:
        return jsonify({"error": "API key obrigatória"}), 400

    enc = _encrypt(api_key)
    row = UserAIKey.query.filter_by(client_id=current_user.id, provider=provider).first()

    if row:
        row.enc_key = enc
    else:
        row = UserAIKey(client_id=current_user.id, provider=provider, enc_key=enc)
        db.session.add(row)
        # Se for a primeira key do usuário, define como padrão automaticamente
        total = UserAIKey.query.filter_by(client_id=current_user.id).count()
        if total == 0:
            row.is_default = True

    db.session.commit()
    return jsonify({"ok": True})


# ── DELETE /api/ai-keys/<provider> ──────────────────────────────────────────

@ai_keys_bp.route("/api/ai-keys/<provider>", methods=["DELETE"])
@login_required
def delete_key(provider):
    row = UserAIKey.query.filter_by(client_id=current_user.id, provider=provider).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return jsonify({"ok": True})


# ── POST /api/ai-keys/<provider>/toggle ─────────────────────────────────────

@ai_keys_bp.route("/api/ai-keys/<provider>/toggle", methods=["POST"])
@login_required
def toggle_key(provider):
    row = UserAIKey.query.filter_by(client_id=current_user.id, provider=provider).first()
    if not row:
        return jsonify({"error": "Chave não encontrada"}), 404
    row.is_active = not row.is_active
    db.session.commit()
    return jsonify({"is_active": row.is_active})


# ── POST /api/ai-keys/<provider>/set-default ────────────────────────────────

@ai_keys_bp.route("/api/ai-keys/<provider>/set-default", methods=["POST"])
@login_required
def set_default(provider):
    row = UserAIKey.query.filter_by(client_id=current_user.id, provider=provider).first()
    if not row:
        return jsonify({"error": "Chave não encontrada"}), 404
    UserAIKey.query.filter_by(client_id=current_user.id).update({"is_default": False})
    row.is_default = True
    db.session.commit()
    return jsonify({"ok": True})


# ── POST /api/ai-keys/<provider>/test ───────────────────────────────────────

@ai_keys_bp.route("/api/ai-keys/<provider>/test", methods=["POST"])
@login_required
def test_key(provider):
    row = UserAIKey.query.filter_by(client_id=current_user.id, provider=provider).first()
    if not row:
        return jsonify({"ok": False, "error": "Nenhuma chave configurada para este provider"}), 404

    if not row.is_active:
        return jsonify({"ok": False, "error": "Provider está desativado"}), 400

    api_key = _decrypt(row.enc_key)
    entry = _TEST_URLS.get(provider)
    if not entry:
        return jsonify({"ok": False, "error": "Provider não suportado"}), 400

    url_or_fn, headers_fn = entry
    url = url_or_fn(api_key) if callable(url_or_fn) else url_or_fn
    headers = headers_fn(api_key)

    try:
        from datetime import datetime, timezone
        resp = _req.get(url, headers=headers, timeout=10)
        if resp.status_code < 400:
            row.last_validated_at = datetime.now(timezone.utc)
            db.session.commit()
            return jsonify({"ok": True, "message": "Conexão bem-sucedida ✓",
                            "last_validated_at": row.last_validated_at.isoformat()})
        return jsonify({"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:120]}"}), 400
    except _req.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Timeout — verifique sua conexão"}), 408
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:120]}), 500
