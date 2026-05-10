"""
Celery tasks de postagem — reutiliza lógica do worker.py.
"""

import logging
import random
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from celery import Task
from celery.utils.log import get_task_logger
from instagrapi.exceptions import (
    LoginRequired, ChallengeRequired, BadPassword,
    PleaseWaitFewMinutes, TwoFactorRequired,
)

from celery_app import celery, make_flask_app

logger = get_task_logger(__name__)
_BRT = ZoneInfo("America/Sao_Paulo")

# ── Flask app (singleton por processo Celery) ─────────────────────
_flask_app = None


def _get_app():
    global _flask_app
    if _flask_app is None:
        _flask_app = make_flask_app()
    return _flask_app


# ── Base Task com app context ─────────────────────────────────────

class ContextTask(Task):
    abstract = True

    def __call__(self, *args, **kwargs):
        with _get_app().app_context():
            return self.run(*args, **kwargs)


# ── Task principal: processar um post ────────────────────────────

@celery.task(
    base=ContextTask,
    bind=True,
    name="tasks.post_tasks.process_post",
    queue="postay.posts",
    max_retries=5,
    # Backoff exponencial: 1min, 2min, 4min, 8min, 16min
    default_retry_delay=60,
    acks_late=True,
)
def process_post(self, post_id: int):
    """
    Processa um único post. Retry automático com backoff exponencial.
    Reutiliza get_ig_client() e process_post() do worker.py.
    """
    from app.models import db, PostQueue, InstagramAccount, Client

    post = db.session.get(PostQueue, post_id)
    if not post:
        logger.warning(f"Post #{post_id} não encontrado — descartando task.")
        return {"ok": False, "reason": "not_found"}

    if post.status not in ("pending", "processing"):
        logger.info(f"Post #{post_id} já está {post.status} — ignorando.")
        return {"ok": False, "reason": f"status={post.status}"}

    account = db.session.get(InstagramAccount, post.account_id)
    if not account:
        post.status = "failed"
        post.error_message = "Conta Instagram não encontrada"
        db.session.commit()
        return {"ok": False, "reason": "no_account"}

    # Marcar como processing
    post.status = "processing"
    db.session.commit()

    # Reutiliza get_ig_client do worker.py
    from worker import get_ig_client, process_post as _process_post

    try:
        cl = get_ig_client(account)
        if not cl:
            # Falha de login — retry com backoff
            post.status = "pending"
            db.session.commit()
            delay = 60 * (2 ** self.request.retries)
            logger.warning(f"Post #{post_id} — falha de login, retry em {delay}s")
            raise self.retry(
                exc=Exception(f"Login falhou para @{account.ig_username}"),
                countdown=delay,
            )

        success = _process_post(post, cl, account)
        logger.info(f"Post #{post_id} — {'OK' if success else 'FALHA'}")
        return {"ok": success, "post_id": post_id}

    except (PleaseWaitFewMinutes, LoginRequired) as exc:
        post.status = "pending"
        db.session.commit()
        delay = 60 * (2 ** self.request.retries)  # 1,2,4,8,16 min
        logger.warning(f"Post #{post_id} — rate limit/sessão, retry em {delay}s")
        raise self.retry(exc=exc, countdown=delay)

    except (self.MaxRetriesExceededError,):
        post.status = "failed"
        post.error_message = f"Falhou após {self.max_retries} tentativas Celery"
        db.session.commit()
        logger.error(f"Post #{post_id} — max retries atingido")
        return {"ok": False, "reason": "max_retries"}

    except Exception as exc:
        # Não faz retry aqui — process_post() já gerencia retry interno
        # só relança se quisermos que Celery também saiba da falha
        logger.error(f"Post #{post_id} — erro inesperado: {exc}")
        if post.status == "processing":
            post.status = "failed"
            post.error_message = str(exc)[:300]
            db.session.commit()
        raise


# ── Scanner: varre DB a cada 5min e enfileira posts ──────────────

@celery.task(
    base=ContextTask,
    bind=True,
    name="tasks.post_tasks.scan_and_enqueue",
    queue="postay.posts",
    max_retries=1,
)
def scan_and_enqueue(self):
    """
    Substitui o loop do daemon worker.py.
    Roda a cada 5min via Beat e enfileira posts pendentes.
    """
    from app.models import db, PostQueue, InstagramAccount

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    pending = (
        PostQueue.query.filter_by(status="pending")
        .filter(
            db.or_(
                PostQueue.scheduled_at.is_(None),
                PostQueue.scheduled_at <= now,
            )
        )
        .order_by(PostQueue.created_at)
        .all()
    )

    if not pending:
        logger.info("scan_and_enqueue: fila vazia.")
        return {"enqueued": 0}

    logger.info(f"scan_and_enqueue: {len(pending)} post(s) encontrado(s)")

    # Limite diário por conta (mesma lógica do worker.py)
    today_start = (
        datetime.now(_BRT)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    MAX_PER_DAY = 3
    daily_count: dict[int, int] = {}

    enqueued = 0
    skipped = 0

    for post in pending:
        acc_id = post.account_id
        if not acc_id:
            acc = InstagramAccount.query.filter_by(
                client_id=post.client_id, status="active"
            ).first()
            if acc:
                acc_id = acc.id
                post.account_id = acc_id
            else:
                post.status = "failed"
                post.error_message = "Nenhuma conta Instagram ativa"
                db.session.commit()
                continue

        if acc_id not in daily_count:
            daily_count[acc_id] = PostQueue.query.filter(
                PostQueue.account_id == acc_id,
                PostQueue.post_type != "story",
                PostQueue.status == "posted",
                PostQueue.post_to_instagram == True,
                PostQueue.posted_at >= today_start,
            ).count()

        if post.post_type != "story" and daily_count[acc_id] >= MAX_PER_DAY:
            skipped += 1
            continue

        # Enfileirar task com delay aleatório para anti-bloqueio
        jitter = random.randint(0, 60)
        process_post.apply_async(
            args=[post.id],
            countdown=jitter,
            queue="postay.posts",
        )

        if post.post_type != "story":
            daily_count[acc_id] = daily_count.get(acc_id, 0) + 1

        enqueued += 1

    logger.info(f"scan_and_enqueue: {enqueued} enfileirado(s), {skipped} ignorado(s) (limite diário)")
    return {"enqueued": enqueued, "skipped": skipped}


# ── Enfileirar imediatamente ao criar post (chamado pelo dashboard) ──

def enqueue_post_now(post_id: int, delay_seconds: int = 5):
    """
    Chamado pelo dashboard quando o usuário cria um post sem agendamento.
    Coloca na fila com delay mínimo para processamento imediato.
    """
    process_post.apply_async(
        args=[post_id],
        countdown=delay_seconds,
        queue="postay.posts",
    )
    logger.info(f"Post #{post_id} enfileirado para processamento em {delay_seconds}s")
