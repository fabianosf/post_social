"""
PostSocial - Aplicação Flask
"""

import logging
import logging.handlers
import os
import secrets
from flask import Flask, jsonify, render_template, request as flask_request
from flask_login import LoginManager
from dotenv import load_dotenv

from .models import db

load_dotenv()

login_manager = LoginManager()


def _configure_logging(app: Flask) -> None:
    """Configura logging estruturado com rotação de arquivo."""
    log_level = logging.DEBUG if app.debug else logging.INFO
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Console handler (sempre)
    ch = logging.StreamHandler()
    ch.setLevel(log_level)
    ch.setFormatter(fmt)

    # File handler com rotação (só se o diretório existir)
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "postay.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.WARNING)
    fh.setFormatter(fmt)

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(log_level)
        root.addHandler(ch)
        root.addHandler(fh)

    # Silencia loggers muito verbosos
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def create_app():
    app = Flask(__name__)
    _configure_logging(app)

    # ProxyFix: confia em 1 nível de proxy (nginx)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key or secret_key == "troque-por-uma-chave-segura":
        secret_key = secrets.token_hex(32)
    app.config["SECRET_KEY"] = secret_key
    # Cookies seguros em produção (HTTPS obrigatório)
    _is_prod = bool(os.environ.get("DATABASE_URL", ""))  # prod tem postgres
    app.config["SESSION_COOKIE_SECURE"]   = _is_prod
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["REMEMBER_COOKIE_SECURE"]  = _is_prod
    _database_url = os.environ.get("DATABASE_URL", "")
    if _database_url:
        # Heroku-style postgres:// → postgresql://
        if _database_url.startswith("postgres://"):
            _database_url = _database_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = _database_url
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
        }
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "postsocial.db"
        )
    app.config["UPLOAD_FOLDER"] = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "uploads"
    )
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max (vídeos)
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1 hora
    app.config["META_PIXEL_ID"] = os.environ.get("META_PIXEL_ID", "").strip()

    if _is_prod:
        _sec_warn = []
        if not os.environ.get("SECRET_KEY", "").strip() or os.environ.get("SECRET_KEY") == "troque-por-uma-chave-segura":
            _sec_warn.append("SECRET_KEY ausente ou padrão — defina no .env")
        if not os.environ.get("FERNET_KEY", "").strip():
            _sec_warn.append("FERNET_KEY ausente — tokens IG não criptografados")
        _fp = os.environ.get("FLOWER_PASS", "")
        if not _fp or _fp == "postay123":
            _sec_warn.append("FLOWER_PASS fraco — use openssl rand -hex 16")
        if not os.environ.get("POSTGRES_PASSWORD", "").strip():
            _sec_warn.append("POSTGRES_PASSWORD ausente")
        for msg in _sec_warn:
            logging.getLogger("postay.security").warning("PROD: %s", msg)

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar o painel."

    from .models import Client

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(Client, int(user_id))
        except (TypeError, ValueError):
            return None

    # ── CORS (Next.js dev em localhost:3000) ──────────────────────
    try:
        from flask_cors import CORS
        _nextjs_origin = os.environ.get("NEXTJS_ORIGIN", "http://localhost:3000")
        CORS(app, origins=[_nextjs_origin], supports_credentials=True,
             allow_headers=["Content-Type", "X-CSRFToken"])
    except ImportError:
        pass

    # ── CSRF protection ───────────────────────────────────────────
    try:
        from flask_wtf.csrf import CSRFProtect
        csrf = CSRFProtect(app)
        app.extensions["csrf"] = csrf
    except ImportError:
        pass  # flask-wtf não instalado

    from .routes_auth import auth_bp
    from .dashboard import dashboard_bp
    from .routes_admin import admin_bp
    from .routes_landing import landing_bp
    from .routes_payment import payment_bp, mp_webhook
    from .routes_tiktok import tiktok_bp
    from .routes_analytics import analytics_bp
    from .routes_recommendations import recommendations_bp
    from .routes_ai import ai_bp
    from .routes_automations import automations_bp
    from .routes_vision import vision_bp
    from .routes_growth import growth_bp
    from .routes_ai_keys import ai_keys_bp
    from .routes_communities import communities_bp
    from .routes_growth_intel import growth_intel_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(landing_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(tiktok_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(recommendations_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(automations_bp)
    app.register_blueprint(vision_bp)
    app.register_blueprint(growth_bp)
    app.register_blueprint(ai_keys_bp)
    app.register_blueprint(communities_bp)
    app.register_blueprint(growth_intel_bp)
    # Endpoints JSON não usam formulários HTML — isentos de CSRF
    if "csrf" in app.extensions:
        app.extensions["csrf"].exempt(ai_keys_bp)
        app.extensions["csrf"].exempt(communities_bp)
        app.extensions["csrf"].exempt(growth_intel_bp)
        app.extensions["csrf"].exempt(mp_webhook)

    # ── Rate limiting ──────────────────────────────────────────────
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[],
            storage_uri="memory://",
        )
        # Proteger login: 10 tentativas por minuto por IP
        from .routes_auth import auth_bp as _auth_bp
        limiter.limit("10 per minute")(auth_bp)
        app.extensions["limiter"] = limiter
    except ImportError:
        pass  # flask-limiter não instalado

    # ── Filtro Jinja2: converte UTC naive → BRT ───────────────────
    from zoneinfo import ZoneInfo as _ZI
    _BRT = _ZI("America/Sao_Paulo")

    @app.template_filter("tobrt")
    def tobrt_filter(dt, fmt="%d/%m %H:%M"):
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=__import__("datetime").timezone.utc)
        return dt.astimezone(_BRT).strftime(fmt)

    # ── Error handlers ────────────────────────────────────────────
    _HTML_404 = (
        '<html><head><meta charset="UTF-8"><title>404 — Postay</title>'
        '<style>body{background:#0f0f0f;color:#e0e0e0;font-family:sans-serif;'
        'display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}'
        'h1{font-size:4rem;color:#7c5cff;margin:0;}a{color:#7c5cff;}</style></head>'
        '<body><div style="text-align:center"><h1>404</h1>'
        '<p>Página não encontrada.</p><a href="/">← Voltar ao início</a></div></body></html>'
    )
    _HTML_500 = (
        '<html><head><meta charset="UTF-8"><title>Erro — Postay</title>'
        '<style>body{background:#0f0f0f;color:#e0e0e0;font-family:sans-serif;'
        'display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}'
        'h1{font-size:4rem;color:#f87171;margin:0;}a{color:#7c5cff;}</style></head>'
        '<body><div style="text-align:center"><h1>500</h1>'
        '<p>Erro interno. Nossa equipe foi notificada.</p><a href="/">← Voltar ao início</a></div></body></html>'
    )

    @app.errorhandler(404)
    def not_found(e):
        if flask_request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        return _HTML_404, 404

    @app.errorhandler(500)
    def server_error(e):
        logging.getLogger(__name__).error("500 em %s: %s", flask_request.path, e)
        if flask_request.path.startswith("/api/"):
            return jsonify({"error": "Erro interno"}), 500
        return _HTML_500, 500

    # ── Security headers ───────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "media-src 'self' blob: data:; "
            "child-src 'self' blob: data:; "
            "script-src 'self' 'unsafe-inline' https://sdk.mercadopago.com https://connect.facebook.net https://www.tiktok.com https://accounts.tiktok.com "
            "https://sf-security.ibytedtos.com https://*.tiktokcdn.com https://*.ttwstatic.com https://mon.tiktokv.com; "
            "script-src-elem 'self' 'unsafe-inline' https://sdk.mercadopago.com https://connect.facebook.net https://www.tiktok.com https://accounts.tiktok.com "
            "https://sf-security.ibytedtos.com https://*.tiktokcdn.com https://*.ttwstatic.com https://mon.tiktokv.com; "
            "style-src 'self' 'unsafe-inline' https://*.ttwstatic.com https://*.tiktokcdn.com; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https://api.mercadopago.com https://connect.facebook.net https://open.tiktokapis.com https://www.tiktok.com https://accounts.tiktok.com "
            "https://sf-security.ibytedtos.com https://*.tiktokcdn.com https://*.ttwstatic.com https://mon.tiktokv.com; "
            "frame-src https://www.mercadopago.com.br https://mercadopago.com.br https://www.tiktok.com https://accounts.tiktok.com "
            "https://sf-security.ibytedtos.com https://*.tiktokcdn.com https://*.ttwstatic.com; "
            "worker-src 'self' blob: https://*.ttwstatic.com https://*.tiktokcdn.com; "
            "form-action 'self' https://www.tiktok.com https://accounts.tiktok.com; "
            "object-src 'none'; "
            "base-uri 'self';"
        )
        return response

    with app.app_context():
        db.create_all()
        from sqlalchemy import text
        _is_sqlite = "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"]
        _is_pg = not _is_sqlite

        # SQLite: usa sintaxe simples (ignora erro se coluna já existe)
        sqlite_migrations = [
            # clients — colunas adicionadas progressivamente
            "ALTER TABLE clients ADD COLUMN gdrive_folder_id VARCHAR(200)",
            "ALTER TABLE clients ADD COLUMN watermark_path VARCHAR(500)",
            "ALTER TABLE clients ADD COLUMN watermark_enabled BOOLEAN DEFAULT 0",
            "ALTER TABLE clients ADD COLUMN watermark_position VARCHAR(20) DEFAULT 'bottom-right'",
            "ALTER TABLE clients ADD COLUMN watermark_opacity INTEGER DEFAULT 80",
            "ALTER TABLE clients ADD COLUMN notify_email BOOLEAN DEFAULT 1",
            "ALTER TABLE clients ADD COLUMN brand_name VARCHAR(100)",
            "ALTER TABLE clients ADD COLUMN brand_color VARCHAR(7)",
            # instagram_accounts
            "ALTER TABLE instagram_accounts ADD COLUMN label VARCHAR(100)",
            "ALTER TABLE instagram_accounts ADD COLUMN status_message TEXT",
            "ALTER TABLE instagram_accounts ADD COLUMN last_login_at TIMESTAMP",
            # post_queue
            "ALTER TABLE post_queue ADD COLUMN post_type VARCHAR(20) DEFAULT 'photo'",
            "ALTER TABLE post_queue ADD COLUMN needs_approval BOOLEAN DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN notified BOOLEAN DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN post_to_instagram BOOLEAN DEFAULT 1",
            "ALTER TABLE post_queue ADD COLUMN post_to_facebook BOOLEAN DEFAULT 1",
            "ALTER TABLE post_queue ADD COLUMN post_to_tiktok BOOLEAN DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN instagram_media_id VARCHAR(100)",
            "ALTER TABLE post_queue ADD COLUMN retry_count INTEGER DEFAULT 0",
            # clients — telegram
            "ALTER TABLE clients ADD COLUMN telegram_bot_token VARCHAR(200)",
            "ALTER TABLE clients ADD COLUMN telegram_chat_id VARCHAR(100)",
            # instagram_accounts — slots recorrentes
            "ALTER TABLE instagram_accounts ADD COLUMN weekday_slots TEXT DEFAULT '[\"09:00\",\"17:00\"]'",
            "ALTER TABLE instagram_accounts ADD COLUMN ig_connection_type VARCHAR(20) DEFAULT 'password'",
            "ALTER TABLE instagram_accounts ADD COLUMN ig_graph_user_id VARCHAR(64)",
            "ALTER TABLE instagram_accounts ADD COLUMN ig_graph_page_id VARCHAR(64)",
            "ALTER TABLE instagram_accounts ADD COLUMN weekend_slots TEXT DEFAULT '[\"10:30\",\"16:00\"]'",
            # clients — bloqueio e Mercado Pago
            "ALTER TABLE clients ADD COLUMN is_blocked BOOLEAN DEFAULT 0",
            "ALTER TABLE clients ADD COLUMN mp_subscription_id VARCHAR(200)",
            "ALTER TABLE clients ADD COLUMN mp_payment_id VARCHAR(200)",
            "ALTER TABLE clients ADD COLUMN plan_expires_at TIMESTAMP",
            # post_queue — métricas de engajamento Instagram
            "ALTER TABLE post_queue ADD COLUMN ig_likes INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN ig_comments INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN ig_views INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN ig_saves INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN ig_reach INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN insights_updated_at TIMESTAMP",
            # clients — conta padrão
            "ALTER TABLE clients ADD COLUMN default_account_id INTEGER REFERENCES instagram_accounts(id)",
            "ALTER TABLE user_ai_keys ADD COLUMN last_validated_at TIMESTAMP",
            "ALTER TABLE post_queue ADD COLUMN ig_permalink VARCHAR(500)",
            "ALTER TABLE post_queue ADD COLUMN ig_media_url VARCHAR(500)",
            "ALTER TABLE post_queue ADD COLUMN fb_post_id VARCHAR(100)",
            "ALTER TABLE post_queue ADD COLUMN fb_permalink VARCHAR(500)",
            "ALTER TABLE post_queue ADD COLUMN fb_error_message TEXT",
            "ALTER TABLE post_queue ADD COLUMN ig_link_error TEXT",
            "ALTER TABLE post_queue ADD COLUMN tiktok_publish_id VARCHAR(100)",
            "ALTER TABLE post_queue ADD COLUMN tiktok_permalink VARCHAR(500)",
            "ALTER TABLE post_queue ADD COLUMN tiktok_link_error TEXT",
            "ALTER TABLE post_queue ADD COLUMN ig_shares INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN fb_views INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN fb_likes INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN fb_comments INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN fb_shares INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN tiktok_video_id VARCHAR(100)",
            "ALTER TABLE post_queue ADD COLUMN tt_views INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN tt_likes INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN tt_comments INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN tt_shares INTEGER DEFAULT 0",
        ]

        # PostgreSQL: usa IF NOT EXISTS (suportado desde PG 9.6)
        pg_migrations = [
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS gdrive_folder_id VARCHAR(200)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS watermark_path VARCHAR(500)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS watermark_enabled BOOLEAN DEFAULT FALSE",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS watermark_position VARCHAR(20) DEFAULT 'bottom-right'",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS watermark_opacity INTEGER DEFAULT 80",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS notify_email BOOLEAN DEFAULT TRUE",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS brand_name VARCHAR(100)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS brand_color VARCHAR(7)",
            "ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS label VARCHAR(100)",
            "ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS status_message TEXT",
            "ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS post_type VARCHAR(20) DEFAULT 'photo'",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS needs_approval BOOLEAN DEFAULT FALSE",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS notified BOOLEAN DEFAULT FALSE",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS post_to_instagram BOOLEAN DEFAULT TRUE",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS post_to_facebook BOOLEAN DEFAULT TRUE",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS post_to_tiktok BOOLEAN DEFAULT FALSE",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS instagram_media_id VARCHAR(100)",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_bot_token VARCHAR(200)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(100)",
            "ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS weekday_slots TEXT DEFAULT '[\"09:00\",\"17:00\"]'",
            "ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS ig_connection_type VARCHAR(20) DEFAULT 'password'",
            "ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS ig_graph_user_id VARCHAR(64)",
            "ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS ig_graph_page_id VARCHAR(64)",
            "ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS weekend_slots TEXT DEFAULT '[\"10:30\",\"16:00\"]'",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS mp_subscription_id VARCHAR(200)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS mp_payment_id VARCHAR(200)",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS plan_expires_at TIMESTAMP",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_likes INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_comments INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_views INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_saves INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_reach INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS insights_updated_at TIMESTAMP",
            "ALTER TABLE clients ADD COLUMN IF NOT EXISTS default_account_id INTEGER REFERENCES instagram_accounts(id)",
            "ALTER TABLE user_ai_keys ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMP",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_permalink VARCHAR(500)",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_media_url VARCHAR(500)",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS fb_post_id VARCHAR(100)",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS fb_permalink VARCHAR(500)",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS fb_error_message TEXT",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_link_error TEXT",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS tiktok_publish_id VARCHAR(100)",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS tiktok_permalink VARCHAR(500)",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS tiktok_link_error TEXT",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS ig_shares INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS fb_views INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS fb_likes INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS fb_comments INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS fb_shares INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS tiktok_video_id VARCHAR(100)",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS tt_views INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS tt_likes INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS tt_comments INTEGER DEFAULT 0",
            "ALTER TABLE post_queue ADD COLUMN IF NOT EXISTS tt_shares INTEGER DEFAULT 0",
        ]

        # user_ai_keys: tabela criada pelo db.create_all() acima
        # Apenas garantir o índice de busca
        # Indexes de performance (idempotentes — IF NOT EXISTS)
        _index_stmts = [
            "CREATE INDEX IF NOT EXISTS ix_post_queue_posted_at ON post_queue (client_id, posted_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_post_queue_client_created ON post_queue (client_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_ai_insights_client_type ON ai_insights (client_id, insight_type, expires_at)",
            "CREATE INDEX IF NOT EXISTS ix_user_ai_keys_client ON user_ai_keys (client_id)",
        ]

        if _is_sqlite:
            with db.engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA synchronous=NORMAL"))
                conn.execute(text("PRAGMA busy_timeout=5000"))
                conn.commit()

    return app
