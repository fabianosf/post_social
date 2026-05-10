"""
Celery tasks de IA — gera e cacheia insights para todos os clientes ativos.
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
    name="tasks.ai_tasks.generate_weekly_ai_insights",
    queue="postay.maintenance",
    max_retries=1,
)
def generate_weekly_ai_insights():
    """
    Roda semanalmente: gera insights de IA para todos os clientes ativos com posts recentes.
    Armazena no cache AIInsight para servir instantaneamente na UI.
    """
    import json
    from datetime import datetime, timezone, timedelta
    from app.models import db, Client, PostQueue, AIInsight
    from app import ai_service

    if not ai_service.is_available():
        logger.info("generate_weekly_ai_insights: IA não configurada, pulando.")
        return {"skipped": True}

    clients = Client.query.filter_by(is_blocked=False).all()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_prev = datetime.now(timezone.utc) - timedelta(days=60)

    processed = errors = skipped = 0

    for client in clients:
        try:
            posts_30 = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= cutoff,
            ).all()

            if not posts_30:
                skipped += 1
                continue

            posts_60 = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= cutoff_prev,
                PostQueue.posted_at < cutoff,
            ).all()

            from app.analytics import post_score, type_performance, period_comparison
            from app.recommendations import detect_patterns

            scored = [p for p in posts_30 if p.instagram_media_id]
            avg_score = round(sum(post_score(p) for p in scored) / len(scored), 2) if scored else 0
            types = type_performance(posts_30)
            comparison = period_comparison(posts_30, posts_60)
            patterns = detect_patterns(posts_30)

            stats = {
                "count": len(posts_30),
                "total_reach": comparison["current"]["reach"],
                "total_likes": comparison["current"]["likes"],
                "total_saves": comparison["current"]["saves"],
                "avg_score": avg_score,
                "reach_growth": comparison["delta"].get("reach", 0),
                "best_type": types[0]["label"] if types else "desconhecido",
                "consistency": patterns.get("consistency", "desconhecida"),
            }

            result = ai_service.generate_ai_insights(stats)
            if result is None:
                errors += 1
                continue

            # Invalida cache antigo, insere novo
            AIInsight.query.filter_by(
                client_id=client.id,
                insight_type="account_insights",
            ).delete()

            expires = datetime.now(timezone.utc) + timedelta(days=7)
            db.session.add(AIInsight(
                client_id=client.id,
                insight_type="account_insights",
                content=json.dumps(result, ensure_ascii=False),
                expires_at=expires,
            ))
            db.session.commit()
            processed += 1

        except Exception as e:
            errors += 1
            logger.warning(f"Cliente #{client.id}: {e}")
            try:
                db.session.rollback()
            except Exception:
                pass

    logger.info(f"generate_weekly_ai_insights: {processed} processados, {skipped} sem posts, {errors} erros.")
    return {"processed": processed, "skipped": skipped, "errors": errors}
