"""
Postay — Growth Tasks (Fase 9)
Pré-computação semanal de scores de crescimento para todos os clientes.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="tasks.growth_tasks.compute_growth_scores")
def compute_growth_scores():
    """Computa e armazena scores de crescimento para todos os clientes ativos."""
    from celery_app import make_flask_app
    app = make_flask_app()

    with app.app_context():
        from app.models import db, Client, PostQueue, AIInsight
        from app import growth as _growth

        clients = Client.query.filter_by(is_blocked=False).all()
        now = datetime.now(timezone.utc)
        cutoff_30  = now - timedelta(days=30)
        cutoff_60  = now - timedelta(days=60)

        processed = 0
        for client in clients:
            try:
                posts_60 = PostQueue.query.filter(
                    PostQueue.client_id == client.id,
                    PostQueue.status == "posted",
                    PostQueue.posted_at >= cutoff_60,
                ).all()

                posts_30 = [p for p in posts_60 if p.posted_at >= cutoff_30]
                posts_prev = [p for p in posts_60 if p not in posts_30]

                if not posts_30:
                    continue

                score_data = _growth.growth_score(posts_30, posts_prev)

                # Invalida cache antigo
                AIInsight.query.filter_by(
                    client_id=client.id,
                    insight_type="growth_score_weekly",
                ).delete()

                row = AIInsight(
                    client_id=client.id,
                    insight_type="growth_score_weekly",
                    content=json.dumps(score_data, ensure_ascii=False),
                    expires_at=now + timedelta(days=8),
                )
                db.session.add(row)
                db.session.commit()
                processed += 1
            except Exception as e:
                db.session.rollback()
                logger.warning(f"growth_score client={client.id}: {e}")

        logger.info(f"compute_growth_scores: {processed}/{len(clients)} clientes processados")
        return {"processed": processed, "total": len(clients)}
