"""
Modelos do banco de dados — PostSocial Micro-SaaS
"""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import os

db = SQLAlchemy()

_fernet_key = os.environ.get("FERNET_KEY", "")
_fernet = Fernet(_fernet_key.encode()) if _fernet_key else None


class Client(UserMixin, db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    # Plano: free (30 posts/mês) | pro (ilimitado)
    plan = db.Column(db.String(20), default="free")
    posts_this_month = db.Column(db.Integer, default=0)
    month_reset = db.Column(db.String(7))  # "2026-03"

    # Watermark
    watermark_path = db.Column(db.String(500))
    watermark_enabled = db.Column(db.Boolean, default=False)
    watermark_position = db.Column(db.String(20), default="bottom-right")
    watermark_opacity = db.Column(db.Integer, default=80)

    # Notificação por email
    notify_email = db.Column(db.Boolean, default=True)

    # White label
    brand_name = db.Column(db.String(100))
    brand_color = db.Column(db.String(7))

    # Google Drive
    gdrive_folder_id = db.Column(db.String(200))   # ID ou URL da pasta

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    instagram_accounts = db.relationship("InstagramAccount", backref="client", lazy=True)
    posts = db.relationship("PostQueue", backref="client", lazy=True)
    templates = db.relationship("CaptionTemplate", backref="client", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_monthly_limit(self) -> int:
        if self.is_admin or self.plan == "pro":
            return 999999
        return 30  # free = 30 posts/mês

    def can_post(self) -> bool:
        if self.is_admin:
            return True
        now = datetime.now(timezone.utc).strftime("%Y-%m")
        if self.month_reset != now:
            self.posts_this_month = 0
            self.month_reset = now
        return self.posts_this_month < self.get_monthly_limit()

    def increment_post_count(self):
        if self.is_admin:
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m")
        if self.month_reset != now:
            self.posts_this_month = 0
            self.month_reset = now
        self.posts_this_month += 1

    def is_pro(self) -> bool:
        return self.is_admin or self.plan == "pro"

    def max_accounts(self) -> int:
        return 999 if self.is_pro() else 1


class InstagramAccount(db.Model):
    __tablename__ = "instagram_accounts"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    ig_username = db.Column(db.String(100), nullable=False)
    ig_password_encrypted = db.Column(db.Text, nullable=False)
    share_to_facebook = db.Column(db.Boolean, default=True)
    label = db.Column(db.String(100))  # "Loja Principal", "Perfil Pessoal"

    status = db.Column(db.String(30), default="active")
    status_message = db.Column(db.Text)

    connected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login_at = db.Column(db.DateTime)

    def set_ig_password(self, password: str):
        if _fernet:
            self.ig_password_encrypted = _fernet.encrypt(password.encode()).decode()
        else:
            self.ig_password_encrypted = password

    def get_ig_password(self) -> str:
        if _fernet:
            return _fernet.decrypt(self.ig_password_encrypted.encode()).decode()
        return self.ig_password_encrypted


class PostQueue(db.Model):
    __tablename__ = "post_queue"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("instagram_accounts.id"))

    # Tipo: photo, album, reels
    post_type = db.Column(db.String(20), default="photo")

    # Arquivos (para album, múltiplos paths separados por |)
    image_path = db.Column(db.String(500), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False)

    caption = db.Column(db.Text)
    hashtags = db.Column(db.Text)

    # Agendamento
    scheduled_at = db.Column(db.DateTime)  # None = postar agora

    # Aprovação: draft (aguardando aprovação), pending (aprovado, na fila), processing, posted, failed
    status = db.Column(db.String(20), default="pending")
    needs_approval = db.Column(db.Boolean, default=False)

    post_to_instagram = db.Column(db.Boolean, default=True)
    post_to_facebook = db.Column(db.Boolean, default=True)

    error_message = db.Column(db.Text)
    instagram_media_id = db.Column(db.String(100))
    notified = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    posted_at = db.Column(db.DateTime)


class CaptionTemplate(db.Model):
    __tablename__ = "caption_templates"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    hashtags = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class WhiteLabelConfig(db.Model):
    __tablename__ = "whitelabel_config"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, unique=True)
    brand_name = db.Column(db.String(100), default="PostSocial")
    brand_color = db.Column(db.String(7), default="#7c5cff")
    brand_logo_url = db.Column(db.String(500))
    custom_domain = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
