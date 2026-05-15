#!/bin/bash
# Atualiza site Postay e recarrega nginx (sem senha após install-nginx-sudoers.sh)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
sudo /usr/bin/install -m 644 -o root -g root "$ROOT/nginx.conf" /etc/nginx/sites-available/postay.com.br
sudo /usr/sbin/nginx -t
sudo /bin/systemctl reload nginx
echo "✓ nginx recarregado"
