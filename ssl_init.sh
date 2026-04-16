#!/bin/bash
set -e

DOMAIN="postay.com.br"
EMAIL="fabiano.freitas@gmail.com"

echo "==> Criando diretórios..."
mkdir -p certbot/www certbot/conf

echo "==> Subindo nginx temporário (só HTTP) para validação ACME..."
# Nginx temporário sem SSL para o certbot poder validar o domínio
docker compose -f docker-compose.prod.yml down 2>/dev/null || true

# Sobe só nginx+web com config HTTP (sem bloco 443)
cat > /tmp/nginx_http_only.conf << 'EOF'
events { worker_connections 1024; }
http {
    upstream postsocial { server web:5000; }
    server {
        listen 80;
        server_name postay.com.br www.postay.com.br;
        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }
        location / {
            proxy_pass http://postsocial;
        }
    }
}
EOF

docker run -d --name nginx-temp \
  -p 80:80 \
  -v /tmp/nginx_http_only.conf:/etc/nginx/nginx.conf:ro \
  -v "$(pwd)/certbot/www:/var/www/certbot" \
  nginx:alpine

echo "==> Emitindo certificado SSL para $DOMAIN..."
docker run --rm \
  -v "$(pwd)/certbot/conf:/etc/letsencrypt" \
  -v "$(pwd)/certbot/www:/var/www/certbot" \
  certbot/certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    -d "www.$DOMAIN"

echo "==> Parando nginx temporário..."
docker stop nginx-temp && docker rm nginx-temp

echo "==> Subindo stack completa de produção com HTTPS..."
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo "✓ Pronto! Site rodando em https://$DOMAIN"
