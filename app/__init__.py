"""
PostSocial - Aplicação Flask
"""

import os
import secrets
from flask import Flask, request as flask_request
from flask_login import LoginManager
from dotenv import load_dotenv

from .models import db

load_dotenv()

login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key or secret_key == "troque-por-uma-chave-segura":
        secret_key = secrets.token_hex(32)
    app.config["SECRET_KEY"] = secret_key
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "postsocial.db"
    )
    app.config["UPLOAD_FOLDER"] = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "uploads"
    )
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max (vídeos)
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1 hora

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar o painel."

    from .models import Client

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Client, int(user_id))

    # ── CSRF protection ───────────────────────────────────────────
    try:
        from flask_wtf.csrf import CSRFProtect
        csrf = CSRFProtect(app)
        app.extensions["csrf"] = csrf
    except ImportError:
        pass  # flask-wtf não instalado

    from .routes_auth import auth_bp
    from .routes_dashboard import dashboard_bp
    from .routes_admin import admin_bp
    from .routes_landing import landing_bp
    from .routes_payment import payment_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(landing_bp)
    app.register_blueprint(payment_bp)

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

    # ── Security headers ───────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    with app.app_context():
        db.create_all()
        # Auto-migração: adiciona colunas novas sem quebrar o banco existente
        from sqlalchemy import text
        migrations = [
            "ALTER TABLE clients ADD COLUMN gdrive_folder_id VARCHAR(200)",
        ]
        with db.engine.connect() as conn:
            for stmt in migrations:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    pass  # Coluna já existe

    return app
