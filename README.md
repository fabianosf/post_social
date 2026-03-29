# PostSocial

Plataforma Micro-SaaS para automação de postagens no Instagram e Facebook para pequenas empresas e agências.

---

## O que é

PostSocial é uma aplicação web multi-tenant que permite gerenciar múltiplos clientes, cada um com suas próprias contas do Instagram, fila de postagens, agendamento inteligente e proteção anti-bloqueio.

Ideal para:
- Agências de marketing gerenciando redes sociais de clientes
- Pequenos negócios que querem automatizar postagens
- Profissionais de social media

---

## Funcionalidades

### Postagens
- Foto simples, carrossel (álbum), Reels (vídeo) e Stories
- Agendamento automático com proteção anti-bloqueio (máx. 5 posts/dia, intervalo ~90min, horários 8h–22h)
- Importação em massa via CSV
- Importação do Google Drive
- Duplicar posts existentes

### Legendas com IA
- Gera 3 opções de legenda automaticamente (via Groq/Llama)
- Templates de legenda reutilizáveis
- Hashtags personalizadas por post

### Proteção Anti-Bloqueio
- Painel de limite diário por conta (feed e stories)
- Distribuição automática de horários com variação aleatória
- Bloqueio de upload quando limite diário é atingido
- Apenas horários seguros (8h às 22h)

### Dashboard
- Preview do post no estilo feed do Instagram
- Calendário de postagens
- Estatísticas completas (mini dashboard)
- Métricas de posts publicados (likes, comentários, views)
- Notificações em tempo real de posts publicados/falhados
- Alertas de sessão expirando

### Pagamento
- Upgrade para plano Pro via PIX (QR Code gerado automaticamente)
- Aprovação manual via painel admin

### White Label
- Personalização de nome e cor do painel por cliente

### Admin
- Visão geral de todos os clientes
- Aprovação de pagamentos PIX
- Gerenciamento de planos (free/pro)

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.12 + Flask |
| Banco de dados | SQLite (via Flask-SQLAlchemy) |
| Autenticação | Flask-Login |
| Instagram | instagrapi |
| IA (legendas) | Groq API (Llama 3.3 70B) via SDK OpenAI |
| Criptografia | Fernet (senhas Instagram) |
| Imagens | Pillow |
| PIX QR Code | EMV BRCode (implementação própria) |
| Frontend | HTML/CSS/JS puro (dark theme) |
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
│   ├── __init__.py           # Factory Flask + registro de blueprints
│   ├── models.py             # Client, InstagramAccount, PostQueue, CaptionTemplate
│   ├── routes_auth.py        # Login, cadastro, logout
│   ├── routes_dashboard.py   # Painel do cliente (upload, agendamento, etc.)
│   ├── routes_admin.py       # Painel administrativo
│   ├── routes_landing.py     # Landing page pública
│   ├── routes_payment.py     # PIX + upgrade Pro
│   └── templates/
│       ├── base.html
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
├── data/                     # Banco SQLite (persistido via volume Docker)
├── uploads/                  # Fotos e vídeos dos clientes
├── sessions/                 # Cache de sessões Instagram
└── logs/                     # Logs do worker
```

---

## Instalação e Uso

### Com Docker (recomendado)

**Pré-requisito:** Docker e Docker Compose instalados.

```bash
# 1. Clonar o projeto
git clone <repo> PostSocial
cd PostSocial

# 2. Configurar variáveis de ambiente
cp .env.example .env
nano .env   # preencha SECRET_KEY, FERNET_KEY e GROQ_API_KEY

# 3. Subir os containers
docker compose up -d

# 4. Criar usuário admin (apenas na primeira vez)
docker compose exec web python3 -c "
from app import create_app; from app.models import db, Client
app = create_app()
with app.app_context():
    db.create_all()
    admin = Client(name='Admin', email='admin@postsocial.com', is_admin=True, plan='pro')
    admin.set_password('admin123')
    db.session.add(admin); db.session.commit()
    print('Admin criado: admin@postsocial.com / admin123')
"
```

Acesse: **http://localhost:5000**

### Comandos Docker

```bash
docker compose up -d             # Subir
docker compose down              # Parar
docker compose restart           # Reiniciar
docker compose logs -f           # Logs em tempo real
docker compose ps                # Status dos containers
docker compose up -d --build     # Rebuild após mudanças no código
docker compose exec web bash     # Terminal dentro do container
```

### Sem Docker (desenvolvimento)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edite o .env com suas chaves

python3 run.py          # servidor web (porta 5000)
python3 worker.py       # worker (ciclo único)
python3 worker.py --daemon --interval=300   # worker daemon
```

---

## Configuração do `.env`

```env
SECRET_KEY=uma-chave-secreta-aleatoria

# Gere com: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=

# Obtenha em: https://console.groq.com
GROQ_API_KEY=

# Opcional
GOOGLE_API_KEY=
```

> **Importante:** Nunca mude o `FERNET_KEY` após salvar senhas do Instagram — as senhas serão perdidas.

---

## Planos

| Recurso | Free | Pro |
|---------|------|-----|
| Posts/mês | 30 | Ilimitado |
| Contas Instagram | 1 | Ilimitado |
| Stories | Não | Sim |
| Import CSV | Não | Sim |
| White Label | Não | Sim |
| Google Drive | Não | Sim |
| Relatório semanal | Não | Sim |
| Preço | Grátis | R$ 49,90/mês (PIX) |

---

## Licença

Projeto privado. Todos os direitos reservados.
