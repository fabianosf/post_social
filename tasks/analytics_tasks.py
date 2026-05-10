"""
Celery task de analytics — refresh noturno de métricas do Instagram.
"""

from celery import Task
from celery.utils.log import get_task_logger

from celery_app import celery, make_flask_app

logger = get_task_logger(__name__)

_flask_app = None


def _get_app():
    global _flask_app
    if _flask_app is None:
        _flask_app = make_flask_app()
    return _flask_app


class ContextTask(Task):
    abstract = True

    def __call__(self, *args, **kwargs):
        with _get_app().app_context():
            return self.run(*args, **kwargs)


@celery.task(
    base=ContextTask,
    name="tasks.analytics_tasks.nightly_refresh",
    queue="postay.maintenance",
    max_retries=1,
)
def nightly_refresh():
    """
    Roda à meia-noite: busca métricas atualizadas do Instagram para todos os clientes.
    Reutiliza lógica de refresh_insights do dashboard.
    """
    from datetime import datetime, timezone, timedelta
    from pathlib import Path
    import os

    from app.models import db, InstagramAccount, PostQueue, Client

    SESSION_DIR = Path(os.path.dirname(os.path.dirname(__file__))) / "sessions"
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    clients = Client.query.filter_by(is_blocked=False).all()
    total_updated = 0
    total_errors = 0

    for client in clients:
        accounts = InstagramAccount.query.filter_by(
            client_id=client.id, status="active"
        ).all()

        for account in accounts:
            session_file = SESSION_DIR / f"account_{account.id}.json"
            if not session_file.exists():
                continue

            try:
                from instagrapi import Client as IGClient
                cl = IGClient()
                cl.delay_range = [1, 3]
                cl.load_settings(session_file)
                cl.get_timeline_feed()

                posts = PostQueue.query.filter(
                    PostQueue.account_id == account.id,
                    PostQueue.status == "posted",
                    PostQueue.posted_at >= week_ago,
                    PostQueue.instagram_media_id.isnot(None),
                ).all()

                for post in posts:
                    try:
                        media_pk = (
                            cl.media_pk_from_code(post.instagram_media_id)
                            if len(post.instagram_media_id) < 15
                            else int(post.instagram_media_id)
                        )
                        info = cl.media_info(media_pk)
                        post.ig_likes = info.like_count or 0
                        post.ig_comments = info.comment_count or 0
                        post.ig_views = (
                            getattr(info, "play_count", None)
                            or getattr(info, "view_count", None)
                            or 0
                        )
                        try:
                            ins = cl.media_insights(media_pk)
                            post.ig_saves = ins.get("saved", 0) or 0
                            post.ig_reach = ins.get("reach", 0) or 0
                        except Exception:
                            pass
                        post.insights_updated_at = now
                        total_updated += 1
                    except Exception as e:
                        total_errors += 1
                        logger.warning(f"Métrica post #{post.id}: {e}")

                db.session.commit()

            except Exception as e:
                total_errors += 1
                logger.warning(f"@{account.ig_username}: {e}")

    logger.info(f"nightly_refresh: {total_updated} posts atualizados, {total_errors} erros.")
    return {"updated": total_updated, "errors": total_errors}
