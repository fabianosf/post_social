#!/bin/bash
# VPS: rotaciona secrets geráveis (não comitar .env).
# META_APP_SECRET / TIKTOK_CLIENT_SECRET / MP_ACCESS_TOKEN: trocar nos portais Meta/TikTok/MP.
set -e
cd "$(dirname "$0")/.."
NEW_SK=$(openssl rand -hex 32)
NEW_FK=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
NEW_PG=$(openssl rand -hex 16)
for kv in "SECRET_KEY=$NEW_SK" "FERNET_KEY=$NEW_FK" "POSTGRES_PASSWORD=$NEW_PG"; do
  k="${kv%%=*}"
  v="${kv#*=}"
  grep -q "^${k}=" .env && sed -i "s|^${k}=.*|${k}=${v}|" .env || echo "${k}=${v}" >> .env
done
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://postay:${NEW_PG}@postgres:5432/postay|" .env
docker compose -f docker-compose.vps.yml exec -T postgres psql -U postay -d postay -c "ALTER USER postay WITH PASSWORD '${NEW_PG}';"
docker compose -f docker-compose.vps.yml up -d web worker celery_worker celery_beat
echo "OK. Reconecte contas Instagram (FERNET_KEY). Sessões web invalidadas (SECRET_KEY)."
