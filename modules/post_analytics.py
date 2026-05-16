"""Métricas por postagem — Instagram, Facebook, TikTok."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

GRAPH = "https://graph.facebook.com/v21.0"
VIDEO_QUERY = "https://open.tiktokapis.com/v2/video/query/?fields=view_count,like_count,comment_count,share_count,id"


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _ig_graph(media_id: str, token: str) -> dict:
    out = {"views": 0, "likes": 0, "comments": 0, "shares": 0}
    try:
        with httpx.Client(timeout=25) as c:
            r = c.get(
                f"{GRAPH}/{media_id}",
                params={"fields": "like_count,comments_count", "access_token": token},
            )
        if r.status_code == 200:
            d = r.json()
            out["likes"] = _int(d.get("like_count"))
            out["comments"] = _int(d.get("comments_count"))
        with httpx.Client(timeout=25) as c:
            r = c.get(
                f"{GRAPH}/{media_id}/insights",
                params={
                    "metric": "impressions,reach,shares",
                    "access_token": token,
                },
            )
        if r.status_code == 200:
            for item in r.json().get("data") or []:
                val = _int((item.get("values") or [{}])[0].get("value"))
                if item.get("name") == "impressions":
                    out["views"] = val
                elif item.get("name") == "reach" and not out["views"]:
                    out["views"] = val
                elif item.get("name") == "shares":
                    out["shares"] = val
    except Exception:
        pass
    return out


def _ig_password(media_id: str, account, session_dir: str) -> dict:
    from modules.metrics import fetch_post_metrics

    raw = fetch_post_metrics(account, media_id, session_dir) or {}
    return {
        "views": _int(raw.get("views")),
        "likes": _int(raw.get("likes")),
        "comments": _int(raw.get("comments")),
        "shares": 0,
    }


def _facebook(post_id: str, token: str) -> dict:
    out = {"views": 0, "likes": 0, "comments": 0, "shares": 0}
    try:
        with httpx.Client(timeout=25) as c:
            r = c.get(
                f"{GRAPH}/{post_id}",
                params={
                    "fields": "shares,likes.summary(true),comments.summary(true)",
                    "access_token": token,
                },
            )
        if r.status_code != 200:
            return out
        d = r.json()
        sh = d.get("shares")
        out["shares"] = _int(sh.get("count") if isinstance(sh, dict) else sh)
        out["likes"] = _int((d.get("likes") or {}).get("summary", {}).get("total_count"))
        out["comments"] = _int((d.get("comments") or {}).get("summary", {}).get("total_count"))
        try:
            with httpx.Client(timeout=25) as c:
                r2 = c.get(
                    f"{GRAPH}/{post_id}/insights",
                    params={"metric": "post_impressions", "access_token": token},
                )
            if r2.status_code == 200:
                for item in r2.json().get("data") or []:
                    if item.get("name") == "post_impressions":
                        out["views"] = _int((item.get("values") or [{}])[0].get("value"))
        except Exception:
            pass
    except Exception:
        pass
    return out


def _tiktok_video_id(post) -> str | None:
    vid = getattr(post, "tiktok_video_id", None)
    if vid:
        return str(vid)
    url = getattr(post, "tiktok_permalink", None) or ""
    m = re.search(r"/video/(\d+)", url)
    return m.group(1) if m else None


def _tiktok(post, client_id: int) -> dict:
    out = {"views": 0, "likes": 0, "comments": 0, "shares": 0}
    vid = _tiktok_video_id(post)
    if not vid:
        return out
    try:
        from app.models import TikTokAccount
        from app.routes_tiktok import get_valid_token, _post_json

        acc = TikTokAccount.query.filter_by(client_id=client_id).first()
        token = get_valid_token(acc) if acc else None
        if not token:
            return out
        resp = _post_json(VIDEO_QUERY, {"filters": {"video_ids": [vid]}}, token)
        if resp.get("error", {}).get("code", "ok") != "ok":
            return out
        for v in (resp.get("data") or {}).get("videos") or []:
            out["views"] = _int(v.get("view_count"))
            out["likes"] = _int(v.get("like_count"))
            out["comments"] = _int(v.get("comment_count"))
            out["shares"] = _int(v.get("share_count"))
            break
    except Exception:
        pass
    return out


def refresh_post_analytics(post, account, session_dir: str | None = None) -> dict:
    """Busca APIs, grava no post. Retorna métricas por plataforma."""
    result: dict = {}
    token = account.get_ig_password() if account else None
    conn = (getattr(account, "ig_connection_type", None) or "password").strip()

    if post.post_to_instagram and post.instagram_media_id and account:
        if conn == "graph_oauth" and token:
            ig = _ig_graph(post.instagram_media_id, token)
        elif session_dir:
            ig = _ig_password(post.instagram_media_id, account, session_dir)
        else:
            ig = {"views": 0, "likes": 0, "comments": 0, "shares": 0}
        post.ig_likes = ig["likes"]
        post.ig_comments = ig["comments"]
        post.ig_views = ig["views"]
        post.ig_shares = ig["shares"]
        result["instagram"] = ig

    if post.fb_post_id and token:
        fb = _facebook(post.fb_post_id, token)
        post.fb_views = fb["views"]
        post.fb_likes = fb["likes"]
        post.fb_comments = fb["comments"]
        post.fb_shares = fb["shares"]
        result["facebook"] = fb

    if post.post_to_tiktok and (post.tiktok_publish_id or post.tiktok_permalink):
        tt = _tiktok(post, post.client_id)
        post.tt_views = tt["views"]
        post.tt_likes = tt["likes"]
        post.tt_comments = tt["comments"]
        post.tt_shares = tt["shares"]
        result["tiktok"] = tt

    post.insights_updated_at = datetime.now(timezone.utc)
    return result
