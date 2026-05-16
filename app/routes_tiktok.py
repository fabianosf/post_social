"""
TikTok Content Posting API — OAuth + publicação de vídeos/fotos.
Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
"""

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

from flask import Blueprint, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user

from .models import db, TikTokAccount

tiktok_bp = Blueprint("tiktok", __name__, url_prefix="/tiktok")

TIKTOK_CLIENT_KEY    = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
_APP_BASE            = (
    os.environ.get("APP_BASE_URL", "").strip()
    or os.environ.get("PUBLIC_BASE_URL", "https://postay.com.br").strip()
).rstrip("/") or "https://postay.com.br"
_DEFAULT_REDIRECT    = f"{_APP_BASE}/tiktok/callback"

# Escopos não concedidos no portal TikTok quebram a página de login (erro genérico «client_key»).
# Padrão: só user.info.basic. Para postar: habilite produtos no app e TIKTOK_OAUTH_SCOPES=user.info.basic,video.publish,video.upload
_raw_scopes = (os.environ.get("TIKTOK_OAUTH_SCOPES", "user.info.basic") or "user.info.basic")
SCOPES = ",".join(s.strip() for s in _raw_scopes.split(",") if s.strip())


def _redirect_uri() -> str:
    """Deve coincidir EXATAMENTE com o URI cadastrado no TikTok Developer Portal."""
    uri = (os.environ.get("TIKTOK_REDIRECT_URI") or _DEFAULT_REDIRECT).strip()
    return uri.rstrip("/")

logger = logging.getLogger(__name__)

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
    code = urllib.parse.unquote((code or "").strip())
    if not code:
        raise RuntimeError("authorization code vazio")
    data = urllib.parse.urlencode({
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": _redirect_uri(),
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(raw[:400] or f"HTTP {e.code}") from e
        msg = data.get("error_description") or data.get("error") or raw[:400]
        raise RuntimeError(str(msg)[:400]) from e


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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(raw[:400] or f"HTTP {e.code}") from e
        msg = data.get("error_description") or data.get("error") or raw[:400]
        raise RuntimeError(str(msg)[:400]) from e


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
    if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
        flash("Configure TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET no .env (ambos obrigatórios).", "error")
        return redirect(url_for("dashboard.index"))

    state = hashlib.sha256(os.urandom(16)).hexdigest()
    session["tiktok_state"] = state
    redirect_uri = _redirect_uri()

    params = urllib.parse.urlencode({
        "client_key": TIKTOK_CLIENT_KEY,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
        "disable_auto_auth": "1",
    })
    resp = redirect(f"{AUTH_URL}?{params}")
    resp.set_cookie(
        "tiktok_oauth_state",
        state,
        max_age=600,
        httponly=True,
        samesite="Lax",
        secure=bool(os.environ.get("DATABASE_URL")),
    )
    return resp


@tiktok_bp.route("/callback")
@login_required
def callback():
    def _cb_redirect():
        r = redirect(url_for("dashboard.index"))
        r.delete_cookie("tiktok_oauth_state")
        return r

    error = request.args.get("error")
    if error:
        err_desc = (request.args.get("error_description") or "").strip()
        flash(f"TikTok: {error}" + (f" — {err_desc[:220]}" if err_desc else ""), "error")
        return _cb_redirect()

    state = request.args.get("state", "")
    expected = session.pop("tiktok_state", None) or request.cookies.get("tiktok_oauth_state")
    if not state or state != expected:
        flash("Estado inválido. Tente novamente.", "error")
        return _cb_redirect()

    code = request.args.get("code")
    if not code:
        flash("Código de autorização não recebido.", "error")
        return _cb_redirect()

    try:
        tok = _exchange_code(code)
        err = tok.get("error") or tok.get("message")
        if err and err not in ("", "ok", None):
            desc = tok.get("error_description") or ""
            flash(f"TikTok: {err}" + (f" — {desc[:200]}" if desc else ""), "error")
            return _cb_redirect()

        access_token  = tok.get("access_token") or tok.get("data", {}).get("access_token", "")
        refresh_token = tok.get("refresh_token") or tok.get("data", {}).get("refresh_token")
        expires_in    = tok.get("expires_in") or tok.get("data", {}).get("expires_in", 86400)
        open_id       = tok.get("open_id") or tok.get("data", {}).get("open_id", "")

        if not access_token or not open_id:
            flash("TikTok não retornou token válido. Tente novamente.", "error")
            return _cb_redirect()

        # Buscar info do usuário
        try:
            info = _get_json(USERINFO_URL, access_token)
            user_data = info.get("data", {}).get("user", {})
        except Exception:
            user_data = {}

        account = TikTokAccount.query.filter_by(client_id=current_user.id, open_id=open_id).first()
        if not account:
            account = TikTokAccount(client_id=current_user.id, open_id=open_id)
            db.session.add(account)

        account.access_token     = access_token
        account.refresh_token    = refresh_token
        account.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        account.username         = user_data.get("username", "")
        account.display_name     = user_data.get("display_name", "")
        account.avatar_url       = user_data.get("avatar_url", "")
        db.session.commit()

        name = account.username or account.display_name or open_id
        flash(f"TikTok @{name} conectado com sucesso!", "success")
    except Exception as e:
        logger.warning("TikTok OAuth callback: %s", e, exc_info=True)
        flash(f"Erro ao conectar TikTok: {str(e)[:280]}", "error")

    return _cb_redirect()


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

    if not os.path.exists(video_path):
        raise Exception(f"Arquivo não encontrado: {video_path}")

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
    if not init_resp.get("data") or init_resp.get("error", {}).get("code", "ok") != "ok":
        raise Exception(f"TikTok video init error: {init_resp.get('error', init_resp)}")

    data = init_resp["data"]
    publish_id  = data.get("publish_id") or ""
    upload_url  = data.get("upload_url") or ""
    if not publish_id or not upload_url:
        raise Exception(f"TikTok não retornou publish_id/upload_url: {data}")

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


def post_photo_to_tiktok(account: TikTokAccount, image_paths: list[str], caption: str) -> str | None:
    """
    Publica foto(s) no TikTok via Content Posting API.
    1 imagem = post simples | múltiplas = carrossel.
    Retorna o publish_id em caso de sucesso.
    """
    token = get_valid_token(account)
    if not token:
        raise Exception("Token TikTok inválido ou expirado.")

    # Verificar arquivos
    missing = [p for p in image_paths if not os.path.exists(p)]
    if missing:
        raise Exception(f"Arquivo(s) não encontrado(s): {missing}")

    # Detectar tipo de imagem
    def _mime(path):
        ext = path.rsplit(".", 1)[-1].lower()
        return "image/webp" if ext == "webp" else "image/jpeg" if ext in ("jpg","jpeg") else "image/png"

    photos_info = []
    for path in image_paths[:35]:  # TikTok aceita até 35 fotos
        size = os.path.getsize(path)
        photos_info.append({"image_size": size})

    init_payload = {
        "post_info": {
            "title": caption[:2200] if caption else "",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_comment": False,
            "auto_add_music": True,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "photo_cover_index": 0,
            "photo_images": photos_info,
        },
        "post_mode": "DIRECT_POST",
        "media_type": "PHOTO",
    }

    init_resp = _post_json(
        "https://open.tiktokapis.com/v2/post/publish/content/init/",
        init_payload, token
    )
    if not init_resp.get("data") or init_resp.get("error", {}).get("code", "ok") != "ok":
        raise Exception(f"TikTok photo init error: {init_resp.get('error', init_resp)}")

    data = init_resp["data"]
    publish_id  = data.get("publish_id") or ""
    upload_urls = data.get("upload_url") or []
    if not publish_id or not upload_urls:
        raise Exception(f"TikTok não retornou publish_id/upload_urls: {data}")

    # Upload de cada imagem
    for path, upload_url in zip(image_paths[:35], upload_urls):
        file_size = os.path.getsize(path)
        with open(path, "rb") as f:
            img_bytes = f.read()
        req = urllib.request.Request(
            upload_url,
            data=img_bytes,
            headers={
                "Content-Type": _mime(path),
                "Content-Range": f"bytes 0-{file_size-1}/{file_size}",
                "Content-Length": str(file_size),
            },
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=60):
            pass

    return publish_id


STATUS_FETCH_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
VIDEO_QUERY_URL = "https://open.tiktokapis.com/v2/video/query/?fields=share_url,id"


def fetch_tiktok_post_url(
    account: TikTokAccount, publish_id: str
) -> tuple[str | None, str | None, str | None]:
    """Após publish: poll status + share_url. Retorna (url, post_id, erro)."""
    token = get_valid_token(account)
    if not token:
        return None, None, "Token TikTok inválido ou expirado"
    username = (account.username or "").strip().lstrip("@")
    last_err = "Aguardando moderação TikTok"
    post_id = None
    for attempt in range(25):
        try:
            resp = _post_json(STATUS_FETCH_URL, {"publish_id": publish_id}, token)
            err = resp.get("error") or {}
            if err.get("code", "ok") != "ok":
                last_err = str(err.get("message") or err)[:400]
            else:
                data = resp.get("data") or {}
                status = data.get("status") or ""
                if status == "FAILED":
                    reason = data.get("fail_reason") or "Falha na publicação"
                    return None, publish_id, f"{reason} (publish_id {publish_id})"
                ids = (
                    data.get("publicaly_available_post_id")
                    or data.get("publicly_available_post_id")
                    or []
                )
                if ids:
                    post_id = str(ids[0])
                if status == "PUBLISH_COMPLETE" and post_id:
                    break
                last_err = f"Status {status}" + (f" (publish_id {publish_id})" if status else "")
        except Exception as e:
            last_err = str(e)[:400]
        if attempt + 1 < 25:
            time.sleep(3)
    if not post_id:
        return None, publish_id, last_err
    share_url = None
    try:
        q = _post_json(
            VIDEO_QUERY_URL,
            {"filters": {"video_ids": [post_id]}},
            token,
        )
        if q.get("error", {}).get("code", "ok") == "ok":
            for v in (q.get("data") or {}).get("videos") or []:
                if v.get("share_url"):
                    share_url = str(v["share_url"])
                    break
    except Exception:
        pass
    if not share_url and username:
        share_url = f"https://www.tiktok.com/@{username}/video/{post_id}"
    elif not share_url:
        share_url = f"https://www.tiktok.com/video/{post_id}"
    return share_url, post_id, None


def post_to_tiktok(account: TikTokAccount, post) -> str | None:
    """
    Função unificada — detecta automaticamente se é vídeo ou foto/carrossel.
    """
    caption = ((post.caption or "") + " " + (post.hashtags or "")).strip()
    paths = post.image_path.split("|")

    if post.post_type in ("reels", "video"):
        return post_video_to_tiktok(account, paths[0], caption)
    else:
        return post_photo_to_tiktok(account, paths, caption)
