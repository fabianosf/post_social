#!/bin/bash
# Checagem rápida de produção (rodar no VPS: bash scripts/prod-check.sh)
set -e
cd "$(dirname "$0")/.."
echo "==> Health"
curl -sf http://127.0.0.1:8095/health | head -c 500 || echo "FAIL web"
echo ""
echo "==> Containers"
docker compose -f docker-compose.vps.yml ps
echo "==> Últimos backups"
ls -lt backups/ 2>/dev/null | head -5 || echo "(sem pasta backups)"
echo "==> Worker heartbeat"
cat logs/worker_heartbeat.txt 2>/dev/null || echo "sem heartbeat"
echo "==> Fila (failed/pending)"
docker compose -f docker-compose.vps.yml exec -T web python -c "
from app import create_app
from app.models import PostQueue
a=create_app()
with a.app_context():
    print('failed', PostQueue.query.filter_by(status='failed').count())
    print('pending', PostQueue.query.filter_by(status='pending').count())
" 2>/dev/null || true
