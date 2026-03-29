"""
PostSocial - Aplicação Flask
"""

import os
from flask import Flask
from flask_login import LoginManager
from dotenv import load_dotenv

from .models import db

load_dotenv()

login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "postsocial-dev-key-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "postsocial.db"
    )
    app.config["UPLOAD_FOLDER"] = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "uploads"
    )
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max (vídeos)

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar o painel."

    from .models import Client

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Client, int(user_id))

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

    with app.app_context():
        db.create_all()

    return app
