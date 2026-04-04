"""
TikTok Content Posting API — OAuth + publicação de vídeos/fotos.
Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
"""

import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

from flask import Blueprint, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user

from .models import db, TikTokAccount

tiktok_bp = Blueprint("tiktok", __name__, url_prefix="/tiktok")

TIKTOK_CLIENT_KEY    = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
TIKTOK_REDIRECT_URI  = os.environ.get("TIKTOK_REDIRECT_URI", "http://localhost:5000/tiktok/callback")

SCOPES = "user.info.basic,video.publish,video.upload"

AUTH_URL    = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL   = "https://open.tiktokapis.com/v2/oauth/token/"
USERINFO_URL= "https://open.tiktokapis.com/v2/user/info/?fields=open_id,union_id,avatar_url,display_name,username"


# ── Helpers ───────────────────────────────────────────────

def _post_json(url: str, payload: dict, token: str = "") -> dict:
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json; charset=UTF-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _exchange_code(code: str) -> dict:
    data = urllib.parse.urlencode({
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": TIKTOK_REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                                  method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _refresh_token(refresh_tok: str) -> dict:
    data = urllib.parse.urlencode({
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                                  method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_valid_token(account: TikTokAccount) -> str | None:
    """Retorna access_token válido, renovando se necessário."""
    now = datetime.now(timezone.utc)
    expires = account.token_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires and now >= expires - timedelta(minutes=10):
        if not account.refresh_token:
            return None
        try:
            resp = _refresh_token(account.refresh_token)
            account.access_token = resp["access_token"]
            account.refresh_token = resp.get("refresh_token", account.refresh_token)
            account.token_expires_at = now + timedelta(seconds=resp.get("expires_in", 86400))
            db.session.commit()
        except Exception:
            return None

    return account.access_token


# ── OAuth ─────────────────────────────────────────────────

@tiktok_bp.route("/connect")
@login_required
def connect():
    if not TIKTOK_CLIENT_KEY:
        flash("Configure TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET no arquivo .env", "error")
        return redirect(url_for("dashboard.index"))

    state = hashlib.sha256(os.urandom(16)).hexdigest()
    session["tiktok_state"] = state

    params = urllib.parse.urlencode({
        "client_key": TIKTOK_CLIENT_KEY,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": TIKTOK_REDIRECT_URI,
        "state": state,
    })
    return redirect(f"{AUTH_URL}?{params}")


@tiktok_bp.route("/callback")
@login_required
def callback():
    error = request.args.get("error")
    if error:
        flash(f"TikTok recusou a autorização: {error}", "error")
        return redirect(url_for("dashboard.index"))

    state = request.args.get("state")
    if state != session.pop("tiktok_state", None):
        flash("Estado inválido. Tente novamente.", "error")
        return redirect(url_for("dashboard.index"))

    code = request.args.get("code")
    if not code:
        flash("Código de autorização não recebido.", "error")
        return redirect(url_for("dashboard.index"))

    try:
        tok = _exchange_code(code)
        access_token  = tok["access_token"]
        refresh_token = tok.get("refresh_token")
        expires_in    = tok.get("expires_in", 86400)
        open_id       = tok["open_id"]

        # Buscar info do usuário
        info = _get_json(USERINFO_URL, access_token)
        user_data = info.get("data", {}).get("user", {})

        account = TikTokAccount.query.filter_by(client_id=current_user.id, open_id=open_id).first()
        if not account:
            account = TikTokAccount(client_id=current_user.id, open_id=open_id)
            db.session.add(account)

        account.access_token     = access_token
        account.refresh_token    = refresh_token
        account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        account.username         = user_data.get("username", "")
        account.display_name     = user_data.get("display_name", "")
        account.avatar_url       = user_data.get("avatar_url", "")
        db.session.commit()

        flash(f"TikTok @{account.username or account.display_name} conectado!", "success")
    except Exception as e:
        flash(f"Erro ao conectar TikTok: {e}", "error")

    return redirect(url_for("dashboard.index"))


@tiktok_bp.route("/disconnect/<int:account_id>", methods=["POST"])
@login_required
def disconnect(account_id):
    account = TikTokAccount.query.filter_by(id=account_id, client_id=current_user.id).first()
    if account:
        db.session.delete(account)
        db.session.commit()
        flash("Conta TikTok desconectada.", "info")
    return redirect(url_for("dashboard.index"))


# ── Posting ───────────────────────────────────────────────

def post_video_to_tiktok(account: TikTokAccount, video_path: str, caption: str) -> str | None:
    """
    Faz upload e publica um vídeo no TikTok via Content Posting API (Direct Post).
    Retorna o publish_id em caso de sucesso, None em caso de falha.
    """
    token = get_valid_token(account)
    if not token:
        raise Exception("Token TikTok inválido ou expirado.")

    file_size = os.path.getsize(video_path)

    # 1. Inicializar upload
    init_payload = {
        "post_info": {
            "title": caption[:2200] if caption else "",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1,
        },
    }
    init_resp = _post_json(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        init_payload, token
    )
    if init_resp.get("error", {}).get("code") != "ok":
        raise Exception(f"TikTok init error: {init_resp}")

    data = init_resp["data"]
    publish_id  = data["publish_id"]
    upload_url  = data["upload_url"]

    # 2. Fazer upload do arquivo
    with open(video_path, "rb") as f:
        video_bytes = f.read()

    upload_req = urllib.request.Request(
        upload_url,
        data=video_bytes,
        headers={
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{file_size-1}/{file_size}",
            "Content-Length": str(file_size),
        },
        method="PUT",
    )
    with urllib.request.urlopen(upload_req, timeout=120):
        pass

    return publish_id
