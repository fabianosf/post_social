"""
Instagram Graph API — OAuth helpers e publicação de foto (feed).
Requer conta Instagram Profissional (Creator/Business) vinculada a uma Página do Facebook.
"""

from __future__ import annotations

import logging
import os
import time
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"

META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")


def oauth_redirect_uri() -> str:
    return os.environ.get(
        "META_OAUTH_REDIRECT_URI",
        "https://postay.com.br/instagram/oauth/callback",
    ).strip()


def oauth_authorize_url(state: str) -> str:
    scopes = ",".join(
        (
            "pages_show_list",
            "pages_read_engagement",
            "pages_manage_posts",
            "instagram_basic",
            "instagram_content_publish",
        )
    )
    q = urllib.parse.urlencode(
        {
            "client_id": META_APP_ID,
            "redirect_uri": oauth_redirect_uri(),
            "scope": scopes,
            "response_type": "code",
            "state": state,
        }
    )
    return f"https://www.facebook.com/v21.0/dialog/oauth?{q}"


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{GRAPH}{path}", params=params)
        try:
            data = r.json()
        except Exception:
            data = {"error": {"message": r.text[:500]}}
        if r.status_code >= 400:
            err = data.get("error", {})
            raise RuntimeError(err.get("message", str(data))[:500])
        return data


def _post(path: str, data: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(f"{GRAPH}{path}", data=data)
        try:
            out = r.json()
        except Exception:
            out = {"error": {"message": r.text[:500]}}
        if r.status_code >= 400:
            err = out.get("error", {})
            raise RuntimeError(err.get("message", str(out))[:500])
        return out


def exchange_code_for_short_user_token(code: str) -> str:
    data = _get(
        "/oauth/access_token",
        {
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "redirect_uri": oauth_redirect_uri(),
            "code": code,
        },
    )
    tok = data.get("access_token")
    if not tok:
        raise RuntimeError("Resposta OAuth sem access_token")
    return str(tok)


def exchange_for_long_lived_user_token(short_user_token: str) -> str:
    data = _get(
        "/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "fb_exchange_token": short_user_token,
        },
    )
    tok = data.get("access_token")
    if not tok:
        raise RuntimeError("Troca por token longo falhou")
    return str(tok)


def exchange_for_long_lived_page_token(page_access_token: str) -> str:
    data = _get(
        "/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": META_APP_ID,
            "client_secret": META_APP_SECRET,
            "fb_exchange_token": page_access_token,
        },
    )
    tok = data.get("access_token")
    if not tok:
        return page_access_token
    return str(tok)


def list_pages_with_instagram(user_access_token: str) -> list[dict[str, Any]]:
    # username inline evita request extra por conta; page token via long-lived user já é long-lived
    raw = _get(
        "/me/accounts",
        {
            "fields": "name,access_token,instagram_business_account{id,username}",
            "access_token": user_access_token,
        },
    )
    rows: list[dict[str, Any]] = []
    for page in raw.get("data", []):
        ig = page.get("instagram_business_account") or {}
        ig_id = ig.get("id")
        if not ig_id:
            continue
        page_token = page.get("access_token") or ""
        if not page_token:
            continue
        ig_username = ig.get("username") or str(ig_id)
        rows.append(
            {
                "page_id": str(page.get("id", "")),
                "page_name": page.get("name", ""),
                "page_access_token": page_token,
                "ig_user_id": str(ig_id),
                "ig_username": str(ig_username).lstrip("@"),
            }
        )
    return rows


def wait_media_container_ready(creation_id: str, access_token: str, timeout: float = 90.0) -> tuple[bool, str | None]:
    deadline = time.time() + timeout
    last_err: str | None = None
    while time.time() < deadline:
        try:
            data = _get(f"/{creation_id}", {"fields": "status_code,status", "access_token": access_token})
        except Exception as e:
            last_err = str(e)
            time.sleep(2.0)
            continue
        code = data.get("status_code")
        if code == "FINISHED":
            return True, None
        if code == "ERROR":
            return False, data.get("status", "Erro ao processar mídia no Instagram")
        time.sleep(2.0)
    return False, last_err or "Timeout aguardando processamento da mídia"


def fetch_media_permalink(
    media_id: str, access_token: str, max_attempts: int = 8
) -> tuple[str | None, str | None, str | None]:
    """Consulta Graph API (permalink, shortcode). Retorna (permalink, media_url, erro)."""
    last_err: str | None = None
    for attempt in range(max_attempts):
        try:
            meta = _get(
                f"/{media_id}",
                {
                    "fields": "permalink,shortcode,media_url",
                    "access_token": access_token,
                },
            )
            permalink = meta.get("permalink")
            shortcode = meta.get("shortcode")
            if not permalink and shortcode:
                permalink = f"https://www.instagram.com/p/{shortcode}/"
            if permalink:
                return str(permalink), meta.get("media_url"), None
            last_err = f"API sem permalink (tentativa {attempt + 1}/{max_attempts})"
            if meta:
                last_err += f": {str(meta)[:200]}"
        except Exception as e:
            last_err = str(e)[:400]
        if attempt + 1 < max_attempts:
            time.sleep(2.0)
    return None, None, last_err


def publish_single_image(
    ig_user_id: str,
    page_access_token: str,
    image_url: str,
    caption: str,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """
    Publica uma imagem no feed do Instagram.
    Retorna (instagram_media_id, erro, permalink, media_url, erro_link).
    """
    cap = (caption or "")[:2200]
    try:
        created = _post(
            f"/{ig_user_id}/media",
            {
                "image_url": image_url,
                "caption": cap,
                "access_token": page_access_token,
            },
        )
    except Exception as e:
        return None, str(e), None, None, None
    creation_id = created.get("id")
    if not creation_id:
        return None, str(created)[:400], None, None, None

    ok, err = wait_media_container_ready(str(creation_id), page_access_token)
    if not ok:
        return None, err or "Falha na fila de mídia", None, None, None

    try:
        pub = _post(
            f"/{ig_user_id}/media_publish",
            {
                "creation_id": str(creation_id),
                "access_token": page_access_token,
            },
        )
    except Exception as e:
        return None, str(e), None, None, None
    mid = pub.get("id")
    if not mid:
        return None, str(pub)[:400], None, None, None
    permalink, media_url, link_err = fetch_media_permalink(str(mid), page_access_token)
    if not permalink:
        logger.warning("permalink IG %s: %s", mid, link_err)
    return str(mid), None, permalink, media_url, link_err
