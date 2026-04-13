# PostSocial

Plataforma Micro-SaaS para automação de postagens no Instagram, Facebook e TikTok para pequenas empresas e agências.

---

## O que é

PostSocial é uma aplicação web multi-tenant que permite gerenciar múltiplos clientes, cada um com suas próprias contas de redes sociais, fila de postagens, agendamento inteligente e proteção anti-bloqueio.

Ideal para:
- Agências de marketing gerenciando redes sociais de clientes
- Pequenos negócios que querem automatizar postagens
- Profissionais de social media

---

## Funcionalidades

### Plataformas suportadas
- **Instagram** — foto, carrossel (álbum), Reels, Stories
- **Facebook** — foto, carrossel, vídeo (simultâneo com Instagram)
- **TikTok** — vídeos (via Content Posting API oficial)

### Postagens
- Foto simples, carrossel (álbum), Reels (vídeo) e Stories
- Agendamento por dia/horário específico escolhido pelo usuário
- Horários recorrentes configuráveis por conta (ex: seg–sex 9h e 17h, sáb–dom 10h30 e 16h)
- Agendamento automático no próximo slot livre disponível
- Grade semanal interativa — visualize e agende em qualquer dia (passados ou futuros)
- Importação em massa via CSV
- Importação do Google Drive
- Retry automático em caso de falha (3 tentativas: 15min → 30min → 60min)

### Notificações
- Telegram: alerta quando post é publicado ✅ ou falha ❌ (configurável por usuário)
- E-mail: notificação de sucesso/falha
- Alertas no painel de sessão expirando

### Legendas com IA
- Gera 3 opções de legenda automaticamente (via Groq/Llama)
- Templates de legenda reutilizáveis
- Hashtags personalizadas por post

### Proteção Anti-Bloqueio
- Limite diário por plataforma (Instagram e Facebook separados)
- Verificação de limite pelo dia do agendamento (não pelo dia atual)
- Fuso horário correto (America/Sao_Paulo → UTC)
- Apenas horários seguros (6h às 22h)

### Dashboard
- Agendamento Semanal com grade visual (todos os dias editáveis)
- Preview do post no estilo feed do Instagram
- Calendário de postagens
- Estatísticas completas (hoje, 7 dias, 30 dias, total, erros, taxa de sucesso)
- Métricas de posts publicados (likes, comentários, views)
- Watermark automática em fotos

### PWA (Progressive Web App)
- Instalável na tela inicial do celular (Android e iPhone)
- Funciona offline para navegação básica
- Ícone e splash screen próprios

### Pagamento
- Upgrade para plano Pro via PIX (QR Code gerado automaticamente)
- Aprovação manual via painel admin

### White Label
- Personalização de nome e cor do painel por cliente

### Admin
- Visão geral de todos os clientes
- Aprovação de pagamentos PIX
- Gerenciamento de planos (free/pro)
- Admin tem acesso total a todos os recursos Pro sem assinatura

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.12 + Flask |
| Banco de dados | SQLite (via Flask-SQLAlchemy) |
| Autenticação | Flask-Login |
| Instagram/Facebook | instagrapi |
| TikTok | Content Posting API (OAuth 2.0 oficial) |
| IA (legendas) | Groq API (Llama 3.3 70B) |
| Notificações | Telegram Bot API + SMTP |
| Criptografia | Fernet (senhas Instagram) |
| Imagens | Pillow |
| PIX QR Code | EMV BRCode (implementação própria) |
| Frontend | HTML/CSS/JS puro (dark theme) + PWA |
| Servidor | Gunicorn |
| Container | Docker + Docker Compose |

---

## Estrutura do Projeto

```
PostSocial/
├── run.py                    # Entrada do servidor Flask
├── worker.py                 # Worker daemon de postagem
├── setup_instagram.py        # Login interativo (2FA/challenge)
├── Dockerfile
├── docker-compose.yml
├── .env                      # Variáveis de ambiente (não commitar)
├── .env.example              # Template do .env
├── requirements.txt
│
├── app/
│   ├── __init__.py           # Factory Flask + registro de blueprints + auto-migração
│   ├── models.py             # Client, InstagramAccount, TikTokAccount, PostQueue, CaptionTemplate
│   ├── routes_auth.py        # Login, cadastro, logout
│   ├── routes_dashboard.py   # Painel do cliente (upload, agendamento, slots recorrentes)
│   ├── routes_admin.py       # Painel administrativo
│   ├── routes_landing.py     # Landing page pública
│   ├── routes_payment.py     # PIX + upgrade Pro
│   ├── routes_tiktok.py      # TikTok OAuth + posting
│   └── templates/
│       ├── base.html         # Layout base (PWA meta tags + service worker)
│       ├── dashboard.html
│       ├── admin.html
│       ├── landing.html
│       ├── login.html
│       ├── register.html
│       ├── payment.html
│       └── stats.html
│
├── modules/
│   ├── caption_generator.py  # Geração de legendas com IA
│   ├── telegram_notify.py    # Notificações via Telegram Bot
│   ├── metrics.py            # Métricas de posts (likes, views)
│   ├── pix.py                # Gerador de QR Code PIX (EMV BRCode)
│   ├── auto_reply.py         # Auto-resposta a comentários
│   ├── weekly_report.py      # Relatório semanal por e-mail
│   ├── gdrive_import.py      # Import do Google Drive
│   ├── instagram_poster.py   # Poster via instagrapi
│   ├── facebook_poster.py    # Poster Facebook (Graph API)
│   ├── file_manager.py       # Gerenciamento de arquivos
│   └── logger.py             # Sistema de logs
│
├── app/static/
│   ├── manifest.json         # PWA manifest
│   ├── sw.js                 # Service Worker
│   └── icons/                # Ícones do app (192x192, 512x512)
│
├── data/                     # Banco SQLite (persistido via volume Docker)
├── uploads/                  # Fotos e vídeos dos clientes
├── sessions/                 # Cache de sessões Instagram
└── logs/                     # Logs do worker
```

---

## Instalação e Uso

### Com Docker (recomendado para produção)

```bash
# 1. Clonar o projeto
git clone <repo> PostSocial
cd PostSocial

# 2. Configurar variáveis de ambiente
cp .env.example .env
nano .env

# 3. Subir os containers
docker compose up -d

# 4. Criar usuário admin (apenas na primeira vez)
docker compose exec web python3 -c "
from app import create_app; from app.models import db, Client
app = create_app()
with app.app_context():
    admin = Client(name='Admin', email='admin@postsocial.com', is_admin=True, plan='pro')
    admin.set_password('admin123')
    db.session.add(admin); db.session.commit()
    print('Admin criado!')
"
```

### Comandos Docker

```bash
docker compose up -d             # Subir
docker compose down              # Parar
docker compose restart           # Reiniciar
docker compose logs -f           # Logs em tempo real
docker compose up -d --build     # Rebuild após mudanças no código
```

### Sem Docker (desenvolvimento)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edite o .env com suas chaves

python3 run.py                              # servidor web (porta 5000)
python3 worker.py --daemon --interval=300  # worker daemon
```

---

## Configuração do `.env`

```env
# Flask
SECRET_KEY=chave-aleatoria-segura

# Criptografia Instagram (NÃO mude após salvar senhas)
FERNET_KEY=

# IA para legendas — https://console.groq.com
GROQ_API_KEY=

# Google Gemini (backup para IA)
GOOGLE_API_KEY=

# PIX
PIX_KEY=seu@email.com
PIX_MERCHANT_NAME=PostSocial
PIX_MERCHANT_CITY=SaoPaulo
PRO_PRICE=49.90

# TikTok Content Posting API — https://developers.tiktok.com
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=https://seudominio.com/tiktok/callback
```

---

## Planos

| Recurso | Free | Pro |
|---------|:----:|:---:|
| Posts no feed/mês | 30 | Ilimitado |
| Stories | — | ✅ |
| Contas Instagram | 1 | Ilimitado |
| TikTok | ✅ | ✅ |
| Import CSV em massa | — | ✅ |
| Import Google Drive | — | ✅ |
| White Label | — | ✅ |
| Agendamento automático | ✅ | ✅ |
| Horários recorrentes | ✅ | ✅ |
| Legendas com IA | ✅ | ✅ |
| Notificações Telegram | ✅ | ✅ |
| Retry automático | ✅ | ✅ |
| PWA (app no celular) | ✅ | ✅ |
| Métricas de posts | ✅ | ✅ |
| Preço | Grátis | R$ 49,90/mês (PIX) |

---

## Configurar TikTok

1. Acesse [developers.tiktok.com](https://developers.tiktok.com)
2. Crie um app e ative o **Content Posting API**
3. Registre o Redirect URI: `https://seudominio.com/tiktok/callback`
4. Copie o **Client Key** e **Client Secret** para o `.env`
5. No dashboard, cada cliente clica **"Conectar TikTok"** e autoriza com a conta dele

---

## Configurar Telegram

1. Acesse [@BotFather](https://t.me/BotFather) no Telegram
2. `/newbot` → copie o **Token**
3. Acesse [@userinfobot](https://t.me/userinfobot) para obter seu **Chat ID**
4. No dashboard, cole o Token e Chat ID na seção **Notificações via Telegram**

---

## Licença

Projeto privado. Todos os direitos reservados.
