"""
Celery task de recomendações — pré-computa perfil e padrões do cliente.
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
    name="tasks.recommendations_tasks.precompute_profiles",
    queue="postay.maintenance",
    max_retries=1,
)
def precompute_profiles():
    """
    Roda semanalmente: detecta padrões e gera recomendações para todos os clientes ativos.
    Apenas loga — os dados já são computados on-demand pelas rotas.
    """
    from datetime import datetime, timezone, timedelta
    from app.models import Client, PostQueue

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    clients = Client.query.filter_by(is_blocked=False).all()
    processed = 0
    errors = 0

    for client in clients:
        try:
            posts = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= cutoff,
            ).all()

            if not posts:
                continue

            from app.recommendations import detect_patterns, client_profile
            profile = client_profile(posts)
            patterns = detect_patterns(posts)

            logger.info(
                f"Client #{client.id}: level={profile['level']}, "
                f"golden_windows={len(patterns['golden_windows'])}, "
                f"consistency={patterns['consistency']}"
            )
            processed += 1
        except Exception as e:
            errors += 1
            logger.warning(f"Erro no cliente #{client.id}: {e}")

    logger.info(f"precompute_profiles: {processed} clientes processados, {errors} erros.")
    return {"processed": processed, "errors": errors}
