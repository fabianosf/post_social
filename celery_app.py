"""
Postay — Celery Application
Broker: Redis | Backend: Redis
"""

import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

celery = Celery(
    "postay",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "tasks.post_tasks",
        "tasks.maintenance_tasks",
        "tasks.analytics_tasks",
    ],
)

celery.conf.update(
    # Serialização
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="America/Sao_Paulo",
    enable_utc=True,

    # Filas
    task_queues={
        "postay.posts": {"exchange": "postay.posts", "routing_key": "posts"},
        "postay.maintenance": {"exchange": "postay.maintenance", "routing_key": "maintenance"},
    },
    task_default_queue="postay.posts",
    task_default_exchange="postay.posts",
    task_default_routing_key="posts",

    # Roteamento por task
    task_routes={
        "tasks.post_tasks.*": {"queue": "postay.posts"},
        "tasks.maintenance_tasks.*": {"queue": "postay.maintenance"},
    },

    # Retry e confiabilidade
    task_acks_late=True,               # ACK só após conclusão (sem perda de task em crash)
    task_reject_on_worker_lost=True,   # Se worker morrer, task volta para a fila
    worker_prefetch_multiplier=1,      # Pega 1 task por vez (fair dispatch entre workers)

    # Resultados
    result_expires=3600,               # Guarda resultados por 1h

    # Beat schedule (substitui o daemon sleep loop)
    beat_schedule={
        "scan-pending-posts": {
            "task": "tasks.post_tasks.scan_and_enqueue",
            "schedule": 300.0,         # A cada 5 minutos
            "options": {"queue": "postay.posts"},
        },
        "run-maintenance": {
            "task": "tasks.maintenance_tasks.run_maintenance",
            "schedule": 3600.0,        # A cada 1 hora
            "options": {"queue": "postay.maintenance"},
        },
        "weekly-reports": {
            "task": "tasks.maintenance_tasks.send_weekly_reports",
            "schedule": 600.0,         # A cada 10 min (a task verifica internamente se é segunda 8h)
            "options": {"queue": "postay.maintenance"},
        },
        "nightly-analytics-refresh": {
            "task": "tasks.analytics_tasks.nightly_refresh",
            "schedule": 86400.0,       # Uma vez por dia (meia-noite)
            "options": {"queue": "postay.maintenance"},
        },
    },
)


# ── Flask app context para tasks ──────────────────────────────────
# Injetado aqui para não criar ciclo de importação em tasks/
def make_flask_app():
    from app import create_app
    return create_app()
