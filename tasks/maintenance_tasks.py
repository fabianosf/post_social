"""
Celery tasks de manutenção — substitui funções periódicas do worker.py.
"""

import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from celery import Task
from celery.utils.log import get_task_logger

from celery_app import celery, make_flask_app

logger = get_task_logger(__name__)
_BRT = ZoneInfo("America/Sao_Paulo")

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
    name="tasks.maintenance_tasks.run_maintenance",
    queue="postay.maintenance",
    max_retries=0,
)
def run_maintenance():
    """Tarefas de manutenção: reset de posts travados, limpeza de arquivos, expiração de planos."""
    from worker import (
        _reset_stuck_processing,
        _cleanup_old_files,
        _check_plan_expirations,
    )
    with _get_app().app_context():
        _reset_stuck_processing()
        _cleanup_old_files()
        _check_plan_expirations()
        _detect_inactive_users()
    logger.info("Manutenção concluída.")
    return {"ok": True}


def _detect_inactive_users():
    """Detecta clientes inativos (sem posts nos últimos 14 dias) e loga para retenção."""
    from app.models import Client, PostQueue
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    clients = Client.query.filter_by(is_blocked=False).all()
    inactive = []
    for c in clients:
        recent = PostQueue.query.filter(
            PostQueue.client_id == c.id,
            PostQueue.created_at >= cutoff,
        ).count()
        if recent == 0:
            days_since = (datetime.now(timezone.utc) - (
                c.created_at.replace(tzinfo=timezone.utc) if c.created_at.tzinfo is None else c.created_at
            )).days
            inactive.append({"id": c.id, "email": c.email, "days_since_creation": days_since})
    if inactive:
        logger.info("Usuários inativos (14d sem posts): %d — ids: %s",
                    len(inactive), [u["id"] for u in inactive])


_last_weekly_report = None


@celery.task(
    base=ContextTask,
    name="tasks.maintenance_tasks.send_weekly_reports",
    queue="postay.maintenance",
    max_retries=0,
)
def send_weekly_reports():
    """Envia relatório semanal. A task roda a cada 10min, mas dispara só segunda às 8h BRT."""
    global _last_weekly_report

    now = datetime.now(timezone.utc)
    now_brt = now.astimezone(_BRT)

    if now_brt.weekday() != 0 or now_brt.hour != 8:
        return {"ok": True, "skipped": True}

    today_key = now_brt.strftime("%Y-%m-%d")
    if _last_weekly_report == today_key:
        return {"ok": True, "skipped": True}
    _last_weekly_report = today_key

    from worker import _send_weekly_reports
    with _get_app().app_context():
        _send_weekly_reports()

    logger.info("Relatórios semanais enviados.")
    return {"ok": True, "date": today_key}


@celery.task(
    base=ContextTask,
    name="tasks.maintenance_tasks.heartbeat",
    queue="postay.maintenance",
    max_retries=0,
)
def heartbeat():
    """Atualiza arquivo de heartbeat para monitoramento externo."""
    from pathlib import Path
    hb = Path("/app/logs/celery_heartbeat.txt")
    hb.parent.mkdir(exist_ok=True)
    hb.write_text(datetime.now(_BRT).strftime("%Y-%m-%d %H:%M:%S BRT"))
    return {"ok": True}
