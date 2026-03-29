# PostSocial — Guia Completo de Instalação e Uso

## 1. Requisitos

- Python 3.10+
- Ubuntu/Linux (ou qualquer OS com Python)
- Conta no Instagram (para postar)
- Chave do Groq (para IA gerar legendas) — [console.groq.com](https://console.groq.com)

---

## 2. Instalação

```bash
# Acessar a pasta do projeto
cd /home/fabianosf/Desktop/PostSocial

# Criar ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
pip install flask flask-login flask-sqlalchemy
pip install instagrapi pillow cryptography python-dotenv
pip install openai   # para Groq/OpenAI IA

# (Opcional) Para Google Drive import
pip install google-api-python-client

# (Opcional) Para Anthropic IA
pip install anthropic
```

---

## 3. Configurar o `.env`

Crie (ou edite) o arquivo `.env` na raiz do projeto:

```bash
# Gerar chave Fernet (copie o resultado)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```env
SECRET_KEY=uma-chave-secreta-qualquer-aqui
FERNET_KEY=cole_a_chave_fernet_gerada_acima

# IA (pelo menos uma)
GROQ_API_KEY=sua_chave_groq_aqui

# (Opcional) Email para notificações e relatórios
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu@email.com
SMTP_PASS=sua_senha_de_app

# (Opcional) Google Drive
GOOGLE_API_KEY=sua_chave_google
GOOGLE_DRIVE_FOLDER_ID=id_da_pasta_no_drive
```

---

## 4. Inicializar o Banco de Dados

```bash
source venv/bin/activate

python3 -c "
from app import create_app
from app.models import db, Client
app = create_app()
with app.app_context():
    db.create_all()
    if not Client.query.filter_by(email='admin@postsocial.com').first():
        admin = Client(name='Admin', email='admin@postsocial.com', is_admin=True, plan='pro')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('Admin criado: admin@postsocial.com / admin123')
    else:
        print('Admin ja existe')
"
```

---

## 5. Rodar a Aplicação Web

```bash
source venv/bin/activate
python3 run.py
```

Acesse: **http://localhost:5000**

| URL | Descrição |
|-----|-----------|
| `/` | Landing page pública (vendas) |
| `/login` | Login |
| `/cadastro` | Cadastro de novo cliente |
| `/dashboard` | Painel do cliente |
| `/admin` | Painel administrativo (somente admins) |

---

## 6. Rodar o Worker (Postagem Automática)

O worker processa a fila e posta no Instagram.

```bash
# Modo único (1 ciclo, para testes)
source venv/bin/activate
python3 worker.py

# Modo daemon (loop contínuo a cada 5 minutos)
python3 worker.py --daemon

# Com intervalo personalizado (ex: 3 minutos)
python3 worker.py --daemon --interval=180
```

### Rodar como serviço no Linux (produção):

```bash
sudo nano /etc/systemd/system/postsocial-worker.service
```

```ini
[Unit]
Description=PostSocial Worker
After=network.target

[Service]
Type=simple
User=fabianosf
WorkingDirectory=/home/fabianosf/Desktop/PostSocial
ExecStart=/home/fabianosf/Desktop/PostSocial/venv/bin/python worker.py --daemon --interval=300
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable postsocial-worker
sudo systemctl start postsocial-worker
sudo journalctl -u postsocial-worker -f   # ver logs
```

### Serviço para o app web:

```bash
sudo nano /etc/systemd/system/postsocial-web.service
```

```ini
[Unit]
Description=PostSocial Web
After=network.target

[Service]
Type=simple
User=fabianosf
WorkingDirectory=/home/fabianosf/Desktop/PostSocial
ExecStart=/home/fabianosf/Desktop/PostSocial/venv/bin/python run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable postsocial-web
sudo systemctl start postsocial-web
```

---

## 7. Todas as Funcionalidades

### Painel do Cliente (`/dashboard`)

| Recurso | Descrição |
|---------|-----------|
| Upload de fotos | Post, carrossel (multiplas fotos), Reels (video) |
| Stories | Marque "Stories" no upload para postar nos stories |
| Legendas com IA | Gera 3 opcoes de legenda, escolha a melhor |
| Preview Instagram | Veja como o post ficara no feed antes de publicar |
| Agendamento | Agende posts para data/hora especifica |
| Templates | Salve e reutilize legendas prontas |
| Marca d'agua | Logo automatica em todas as fotos |
| Import CSV | Importe 30+ posts de uma vez via planilha |
| Google Drive | Importe fotos de uma pasta do Drive |
| Duplicar post | Botao para repostar conteudo existente |
| Metricas | Veja likes, comentarios e views dos posts |
| Melhor horario | IA sugere os melhores horarios para postar |
| White Label | Personalize nome e cor do painel |
| Notificacoes | Alertas de posts publicados/falhados em tempo real |
| Alertas de sessao | Aviso quando sessao do Instagram vai expirar |

### Painel Admin (`/admin`)
- Visao geral de todos os clientes e posts
- Grafico de posts dos ultimos 7 dias
- Alterar plano de clientes (free/pro)
- Reenviar ou excluir posts com erro

---

## 8. Auto-Reply e Relatorio Semanal (Cron)

```bash
crontab -e
```

```cron
# Relatorio semanal (toda segunda as 8h)
0 8 * * 1 cd /home/fabianosf/Desktop/PostSocial && venv/bin/python -m modules.weekly_report

# Auto-reply a comentarios (a cada 2 horas)
0 */2 * * * cd /home/fabianosf/Desktop/PostSocial && venv/bin/python -m modules.auto_reply
```

---

## 9. Primeiro Teste (Passo a Passo)

1. `source venv/bin/activate && python3 run.py`
2. Abra `http://localhost:5000` — veja a landing page
3. Clique "Comecar Gratis" ou va para `/login`
4. Login: `admin@postsocial.com` / `admin123`
5. Clique "Conectar Instagram" e coloque usuario e senha
6. Se pedir verificacao, rode: `python3 setup_instagram.py`
7. Suba uma foto, clique "Gerar 3 opcoes com IA", escolha uma legenda
8. Marque "Stories" se quiser postar tambem nos stories
9. Clique "Enviar"
10. Em outro terminal: `source venv/bin/activate && python3 worker.py`
11. O worker posta no Instagram automaticamente

---

## 10. Formato do CSV para Import em Massa

```csv
filename,caption,hashtags,scheduled_at
foto1.jpg,Confira nossa novidade!,#loja #novidade,2026-04-01 10:00
foto2.jpg,,,2026-04-02 14:00
foto3.jpg,Promocao imperdivel!,#promo,
video.mp4,Veja este reel!,#reels,2026-04-03 18:00
```

- **filename** — nome exato do arquivo (enviado junto com o CSV)
- **caption** — legenda (vazio = IA gera automaticamente)
- **hashtags** — hashtags (opcional)
- **scheduled_at** — formato `YYYY-MM-DD HH:MM` (opcional)

---

## 11. Estrutura do Projeto

```
PostSocial/
├── run.py                    # Iniciar app web
├── worker.py                 # Worker de postagem
├── setup_instagram.py        # Login interativo (challenge)
├── .env                      # Variaveis de ambiente
├── data/postsocial.db        # Banco SQLite
├── uploads/                  # Fotos dos clientes
├── sessions/                 # Sessoes Instagram
├── logs/                     # Logs do worker
├── app/
│   ├── __init__.py           # Factory Flask
│   ├── models.py             # Modelos do banco
│   ├── routes_auth.py        # Login/cadastro
│   ├── routes_dashboard.py   # Dashboard
│   ├── routes_admin.py       # Painel admin
│   ├── routes_landing.py     # Landing page
│   └── templates/
│       ├── base.html         # Layout base (dark theme)
│       ├── dashboard.html    # Painel principal
│       ├── admin.html        # Painel admin
│       ├── landing.html      # Pagina de vendas
│       ├── login.html        # Login
│       └── register.html     # Cadastro
└── modules/
    ├── caption_generator.py  # IA multi-provider (Groq, OpenAI, etc)
    ├── metrics.py            # Metricas de posts (likes, views)
    ├── auto_reply.py         # Auto-reply a comentarios
    ├── weekly_report.py      # Relatorio semanal por email
    ├── gdrive_import.py      # Import do Google Drive
    ├── instagram_poster.py   # Poster original
    ├── facebook_poster.py    # Facebook poster
    ├── file_manager.py       # Gerenciador de arquivos
    └── logger.py             # Sistema de logs
```

---

## 12. Docker (Recomendado para producao)

### Requisitos
- Docker e Docker Compose instalados

### Configurar

```bash
# 1. Copie o arquivo de exemplo e preencha com suas chaves
cp .env.example .env
nano .env
```

### Subir o projeto

```bash
# Subir web + worker (primeira vez faz o build)
docker compose up -d

# Verificar se os containers estao rodando
docker compose ps
```

Resultado esperado:
```
NAME                 STATUS
postsocial-web       Up
postsocial-worker    Up
```

Acesse: **http://localhost:5000**

### Ver logs

```bash
# Todos os logs (web + worker)
docker compose logs -f

# Apenas o web
docker compose logs -f web

# Apenas o worker
docker compose logs -f worker

# Ultimas 50 linhas
docker compose logs --tail 50
```

### Parar o projeto

```bash
# Parar tudo (mantém dados)
docker compose down

# Parar e remover volumes (CUIDADO: apaga banco e uploads)
docker compose down -v
```

### Reiniciar

```bash
# Reiniciar tudo
docker compose restart

# Reiniciar apenas o worker
docker compose restart worker

# Reiniciar apenas o web
docker compose restart web
```

### Atualizar apos mudancas no codigo

```bash
# Rebuild e reiniciar
docker compose up -d --build
```

### Criar usuario admin (primeira vez)

```bash
docker compose exec web python3 -c "
from app import create_app
from app.models import db, Client
app = create_app()
with app.app_context():
    db.create_all()
    if not Client.query.filter_by(email='admin@postsocial.com').first():
        admin = Client(name='Admin', email='admin@postsocial.com', is_admin=True, plan='pro')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('Admin criado: admin@postsocial.com / admin123')
    else:
        print('Admin ja existe')
"
```

### Comandos uteis Docker

```bash
# Entrar no container (terminal interativo)
docker compose exec web bash

# Ver uso de recursos (CPU, memoria)
docker stats postsocial-web postsocial-worker

# Ver tamanho das imagens
docker images | grep postsocial

# Limpar imagens antigas (liberar espaco)
docker image prune -f
```

### Volumes (dados persistentes)

Os dados ficam na sua maquina, nao dentro do container:

| Pasta local | Descricao |
|-------------|-----------|
| `./data/` | Banco de dados SQLite |
| `./uploads/` | Fotos e videos dos clientes |
| `./sessions/` | Sessoes do Instagram |
| `./logs/` | Logs do worker e app |

Mesmo rodando `docker compose down`, esses dados sao mantidos.

---

## 13. Comandos Rapidos

### Sem Docker (desenvolvimento)

```bash
source venv/bin/activate         # Ativar ambiente
python3 run.py                   # Rodar web (porta 5000)
python3 worker.py                # Worker (1 ciclo)
python3 worker.py --daemon       # Worker (loop continuo)
python3 setup_instagram.py       # Setup Instagram (challenge)
python3 -m modules.weekly_report # Relatorio semanal
python3 -m modules.auto_reply    # Auto-reply manual
```

### Com Docker (producao)

```bash
docker compose up -d             # Subir tudo
docker compose down              # Parar tudo
docker compose restart           # Reiniciar tudo
docker compose logs -f           # Ver logs em tempo real
docker compose ps                # Ver status dos containers
docker compose up -d --build     # Rebuild apos mudancas
docker compose exec web bash     # Terminal dentro do container
```
