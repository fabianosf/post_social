#!/bin/bash
# Uso único no VPS: sudo bash scripts/install-nginx-sudoers.sh
set -e
[[ $(id -u) -eq 0 ]] || { echo "Execute com sudo."; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
install -m 440 -o root -g root "$ROOT/deploy/sudoers-postay-nginx" /etc/sudoers.d/postay-nginx
visudo -c -f /etc/sudoers.d/postay-nginx
echo "✓ sudoers postay-nginx instalado"
