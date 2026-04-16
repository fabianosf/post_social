#!/bin/bash
# deploy.sh — Push para GitHub e deploy no VPS em um comando
set -e

VPS_USER="fabianosf"
VPS_HOST="92.113.33.16"
VPS_DIR="~/post_social"
COMPOSE="docker-compose.vps.yml"

echo "==> [1/4] Verificando mudanças..."
cd "$(dirname "$0")"

if [[ -z "$(git status --porcelain)" ]]; then
    echo "    Nada para commitar, apenas fazendo deploy."
else
    echo "    Arquivos modificados:"
    git status --short
    echo ""
    read -p "    Mensagem do commit: " MSG
    if [[ -z "$MSG" ]]; then
        MSG="deploy: atualização $(date '+%d/%m/%Y %H:%M')"
    fi
    git add -A
    git commit -m "$MSG"
fi

echo ""
echo "==> [2/4] Push para GitHub..."
git push origin master
echo "    ✓ GitHub atualizado"

echo ""
echo "==> [3/4] Atualizando VPS..."
ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "
    set -e
    cd $VPS_DIR
    git pull origin master
    echo '    ✓ Código atualizado'
"

echo ""
echo "==> [4/4] Rebuilding containers no VPS..."
ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "
    cd $VPS_DIR
    docker compose -f $COMPOSE up -d --build
    sleep 5
    docker compose -f $COMPOSE ps
"

echo ""
echo "✓ Deploy concluído! https://postay.com.br"
