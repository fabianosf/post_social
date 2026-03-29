"""
Métricas de posts — Puxa likes, comentários e alcance via instagrapi.
"""

from pathlib import Path


def fetch_post_metrics(account, post_media_id: str, session_dir: str) -> dict | None:
    """
    Busca métricas de um post pelo media_id.
    Retorna dict com likes, comments, etc.
    """
    try:
        from instagrapi import Client as IGClient
    except ImportError:
        return None

    if not post_media_id:
        return None

    cl = IGClient()
    session_file = Path(session_dir) / f"account_{account.id}.json"

    if not session_file.exists():
        return None

    try:
        cl.load_settings(session_file)
        cl.login(account.ig_username, account.get_ig_password())

        media_info = cl.media_info(int(post_media_id))
        return {
            "likes": media_info.like_count,
            "comments": media_info.comment_count,
            "views": getattr(media_info, "view_count", 0) or 0,
            "taken_at": str(media_info.taken_at) if media_info.taken_at else None,
            "media_type": str(media_info.media_type),
        }
    except Exception:
        return None


def fetch_account_insights(account, session_dir: str) -> dict | None:
    """
    Busca insights gerais da conta (seguidores, posts recentes).
    """
    try:
        from instagrapi import Client as IGClient
    except ImportError:
        return None

    cl = IGClient()
    session_file = Path(session_dir) / f"account_{account.id}.json"

    if not session_file.exists():
        return None

    try:
        cl.load_settings(session_file)
        cl.login(account.ig_username, account.get_ig_password())

        user_info = cl.user_info_by_username(account.ig_username)
        return {
            "followers": user_info.follower_count,
            "following": user_info.following_count,
            "posts_count": user_info.media_count,
            "bio": user_info.biography,
        }
    except Exception:
        return None
