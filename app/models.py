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

    # Notificação via Telegram
    telegram_bot_token = db.Column(db.String(200))
    telegram_chat_id = db.Column(db.String(100))

    # White label
    brand_name = db.Column(db.String(100))
    brand_color = db.Column(db.String(7))

    # Google Drive
    gdrive_folder_id = db.Column(db.String(200))   # ID ou URL da pasta

    # Conta Instagram padrão para novos posts (sem FK declarada para evitar ambiguidade no ORM)
    default_account_id = db.Column(db.Integer, nullable=True)

    # Controle de acesso
    is_blocked = db.Column(db.Boolean, default=False)

    # Mercado Pago
    mp_subscription_id = db.Column(db.String(200))
    mp_payment_id = db.Column(db.String(200))
    plan_expires_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    instagram_accounts = db.relationship("InstagramAccount", backref="client", lazy=True)
    posts = db.relationship("PostQueue", backref="client", lazy=True)
    templates = db.relationship("CaptionTemplate", backref="client", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def _check_plan_expiry(self):
        """Rebaixa para Free se plano pago expirou."""
        if self.plan in ("pro", "agency") and not self.is_admin and self.plan_expires_at:
            expires = self.plan_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires:
                self.plan = "free"
                self.mp_subscription_id = None
                self.plan_expires_at = None
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

    def is_paid(self) -> bool:
        if self.is_admin:
            return True
        self._check_plan_expiry()
        return self.plan in ("pro", "agency")

    def get_monthly_limit(self) -> int:
        if self.is_admin or self.is_paid():
            return 999999
        return 30  # free = 30 posts/mês

    def can_post(self) -> bool:
        if self.is_admin:
            return True
        self._check_plan_expiry()
        if self.is_blocked:
            return False
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

    def has_pro_features(self) -> bool:
        """Pro + Agency: posts ilimitados, stories, CSV, IA visual, automações, growth."""
        return self.is_paid()

    def is_pro(self) -> bool:
        return self.has_pro_features()

    def is_agency(self) -> bool:
        if self.is_admin:
            return True
        self._check_plan_expiry()
        return self.plan == "agency"

    def max_competitors(self) -> int:
        if self.is_admin or self.is_agency():
            return 15
        if self.has_pro_features():
            return 5
        return 0

    def max_accounts(self) -> int:
        if self.is_admin:
            return 999
        if self.plan == "agency":
            return 10
        if self.plan == "pro":
            return 3
        return 1


class InstagramAccount(db.Model):
    __tablename__ = "instagram_accounts"
    __table_args__ = (
        db.Index("ix_ig_accounts_client_id", "client_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    ig_username = db.Column(db.String(100), nullable=False)
    ig_password_encrypted = db.Column(db.Text, nullable=False)
    share_to_facebook = db.Column(db.Boolean, default=True)
    label = db.Column(db.String(100))  # "Loja Principal", "Perfil Pessoal"

    status = db.Column(db.String(30), default="active")
    status_message = db.Column(db.Text)

    # Slots recorrentes: JSON list de "HH:MM", ex: '["09:00","17:00"]'
    weekday_slots = db.Column(db.Text, default='["09:00","17:00"]')   # Seg–Sex
    weekend_slots = db.Column(db.Text, default='["10:30","16:00"]')   # Sáb–Dom

    connected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login_at = db.Column(db.DateTime)

    # password | session | graph_oauth — graph_oauth usa token da Página (Meta API oficial)
    ig_connection_type = db.Column(db.String(20), default="password")
    ig_graph_user_id = db.Column(db.String(64), nullable=True)
    ig_graph_page_id = db.Column(db.String(64), nullable=True)

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
    __table_args__ = (
        db.Index("ix_post_queue_client_status", "client_id", "status"),
        db.Index("ix_post_queue_account_scheduled", "account_id", "scheduled_at"),
        db.Index("ix_post_queue_status_scheduled", "status", "scheduled_at"),
    )

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
    post_to_tiktok = db.Column(db.Boolean, default=False)

    error_message = db.Column(db.Text)
    instagram_media_id = db.Column(db.String(100))
    ig_permalink = db.Column(db.Text)
    ig_media_url = db.Column(db.Text)
    ig_link_error = db.Column(db.Text)
    fb_post_id = db.Column(db.String(100))
    fb_permalink = db.Column(db.Text)
    fb_error_message = db.Column(db.Text)
    tiktok_publish_id = db.Column(db.String(100))
    tiktok_permalink = db.Column(db.Text)
    tiktok_link_error = db.Column(db.Text)
    notified = db.Column(db.Boolean, default=False)
    retry_count = db.Column(db.Integer, default=0)

    # Métricas de engajamento (atualizadas via refresh)
    ig_likes = db.Column(db.Integer, default=0)
    ig_comments = db.Column(db.Integer, default=0)
    ig_views = db.Column(db.Integer, default=0)
    ig_saves = db.Column(db.Integer, default=0)
    ig_reach = db.Column(db.Integer, default=0)
    ig_shares = db.Column(db.Integer, default=0)
    fb_views = db.Column(db.Integer, default=0)
    fb_likes = db.Column(db.Integer, default=0)
    fb_comments = db.Column(db.Integer, default=0)
    fb_shares = db.Column(db.Integer, default=0)
    tiktok_video_id = db.Column(db.String(100))
    tt_views = db.Column(db.Integer, default=0)
    tt_likes = db.Column(db.Integer, default=0)
    tt_comments = db.Column(db.Integer, default=0)
    tt_shares = db.Column(db.Integer, default=0)
    insights_updated_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    posted_at = db.Column(db.DateTime)


class TikTokAccount(db.Model):
    __tablename__ = "tiktok_accounts"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    open_id = db.Column(db.String(200), nullable=False)       # ID único do usuário no TikTok
    username = db.Column(db.String(100))
    display_name = db.Column(db.String(200))
    avatar_url = db.Column(db.String(500))
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    connected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    client = db.relationship("Client", backref="tiktok_accounts")


class CaptionTemplate(db.Model):
    __tablename__ = "caption_templates"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    hashtags = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AIInsight(db.Model):
    """Cache de resultados de IA — evita re-chamar a API para mesmos dados."""
    __tablename__ = "ai_insights"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post_queue.id"), nullable=True)
    insight_type = db.Column(db.String(50), nullable=False)  # account_insights, virality, caption, etc.
    content = db.Column(db.Text, nullable=False)             # JSON
    tokens_used = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True)


class AutomationAlert(db.Model):
    """Alertas gerados automaticamente pela task diária ou por triggers."""
    __tablename__ = "automation_alerts"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    alert_type = db.Column(db.String(50), nullable=False)    # engagement_drop, frequency_low, viral_detected…
    severity = db.Column(db.String(10), default="info")      # error | warning | success | info
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    action = db.Column(db.String(100))                       # label do botão de ação (opcional)
    action_url = db.Column(db.String(500))                   # URL da ação (opcional)
    is_dismissed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True)


class GrowthGoal(db.Model):
    """Metas de crescimento definidas pelo cliente."""
    __tablename__ = "growth_goals"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    goal_type = db.Column(db.String(30), nullable=False)     # reach | likes | posts_week | score
    label = db.Column(db.String(100))                        # nome amigável definido pelo usuário
    target_value = db.Column(db.Float, nullable=False)
    period = db.Column(db.String(20), default="monthly")    # weekly | monthly
    deadline = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    achieved_at = db.Column(db.DateTime, nullable=True)


class UserAIKey(db.Model):
    """API keys de IA por usuário — armazenadas criptografadas com Fernet."""
    __tablename__ = "user_ai_keys"

    id         = db.Column(db.Integer, primary_key=True)
    client_id  = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    provider   = db.Column(db.String(50), nullable=False)
    enc_key    = db.Column(db.Text, nullable=False)
    is_active         = db.Column(db.Boolean, default=True)
    is_default        = db.Column(db.Boolean, default=False)
    last_validated_at = db.Column(db.DateTime, nullable=True)
    created_at        = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint("client_id", "provider", name="uq_user_ai_provider"),)


class WhiteLabelConfig(db.Model):
    __tablename__ = "whitelabel_config"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, unique=True)
    brand_name = db.Column(db.String(100), default="Postay")
    brand_color = db.Column(db.String(7), default="#7c5cff")
    brand_logo_url = db.Column(db.String(500))
    custom_domain = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Community(db.Model):
    __tablename__ = "communities"

    id               = db.Column(db.Integer, primary_key=True)
    platform         = db.Column(db.String(20), nullable=False)   # telegram, reddit, discord
    name             = db.Column(db.String(200), nullable=False)
    description      = db.Column(db.Text)
    url              = db.Column(db.String(500))
    niche            = db.Column(db.String(100), index=True)
    category         = db.Column(db.String(100), index=True)      # categoria ampla: negocios, saude, etc.
    city             = db.Column(db.String(100), index=True)
    member_count     = db.Column(db.Integer, default=0)
    tags             = db.Column(db.Text, default="[]")           # JSON array
    engagement_score = db.Column(db.Float, default=0.0)           # 0-100, setado pelo admin
    verified         = db.Column(db.Boolean, default=False)       # curado manualmente
    tone             = db.Column(db.String(50), default="casual") # casual, formal, educativo, humoristico
    rules            = db.Column(db.Text, default="[]")           # JSON array de regras da comunidade
    is_active        = db.Column(db.Boolean, default=True)
    is_spam          = db.Column(db.Boolean, default=False)
    is_dead          = db.Column(db.Boolean, default=False)
    last_activity_at = db.Column(db.DateTime, nullable=True)
    created_at       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def tags_list(self) -> list:
        import json
        try:
            return json.loads(self.tags or "[]")
        except Exception:
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "niche": self.niche,
            "category": self.category,
            "city": self.city,
            "member_count": self.member_count,
            "engagement_score": self.engagement_score,
            "verified": self.verified,
            "tone": self.tone,
            "rules": self.rules_list(),
            "is_dead": self.is_dead,
            "is_spam": self.is_spam,
            "tags": self.tags_list(),
        }

    def rules_list(self) -> list:
        import json
        try:
            return json.loads(self.rules or "[]")
        except Exception:
            return []


class UserNiche(db.Model):
    __tablename__ = "user_niches"

    user_id     = db.Column(db.Integer, db.ForeignKey("clients.id"), primary_key=True)
    niche       = db.Column(db.String(100))
    keywords    = db.Column(db.Text, default="[]")   # JSON array
    confidence  = db.Column(db.Float, default=0.0)
    detected_at = db.Column(db.DateTime)

    def keywords_list(self) -> list:
        import json
        try:
            return json.loads(self.keywords or "[]")
        except Exception:
            return []


class Competitor(db.Model):
    """Concorrentes cadastrados manualmente pelo usuário para benchmarking."""
    __tablename__ = "competitors"

    id           = db.Column(db.Integer, primary_key=True)
    client_id    = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    name         = db.Column(db.String(200), nullable=False)
    niche        = db.Column(db.String(100))
    ig_username  = db.Column(db.String(100))
    website_url  = db.Column(db.String(500))
    notes        = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "niche": self.niche,
            "ig_username": self.ig_username,
            "website_url": self.website_url,
            "notes": self.notes,
        }


class NicheTrend(db.Model):
    """Cache de tendências por nicho geradas por IA. Atualizado periodicamente."""
    __tablename__ = "niche_trends"

    niche      = db.Column(db.String(100), primary_key=True)
    trend_data = db.Column(db.Text, default="{}")   # JSON
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def data(self) -> dict:
        import json
        try:
            return json.loads(self.trend_data or "{}")
        except Exception:
            return {}
