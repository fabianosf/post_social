"""
Painel Administrativo — Visão geral de todos os clientes, posts e sistema.
Acessível apenas por usuários com is_admin=True.
"""

import os
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from .models import db, Client, InstagramAccount, PostQueue

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash("Acesso restrito ao administrador.", "error")
            return redirect(url_for("dashboard.index"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/")
@admin_required
def index():
    clients = Client.query.order_by(Client.created_at.desc()).all()

    # Stats globais
    total_posts = PostQueue.query.count()
    posted = PostQueue.query.filter_by(status="posted").count()
    pending = PostQueue.query.filter_by(status="pending").count()
    failed = PostQueue.query.filter_by(status="failed").count()
    drafts = PostQueue.query.filter_by(status="draft").count()

    # Posts hoje
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    posted_today = PostQueue.query.filter(
        PostQueue.status == "posted",
        PostQueue.posted_at >= today,
    ).count()

    # Posts últimos 7 dias (para gráfico)
    weekly_data = []
    for i in range(6, -1, -1):
        day = datetime.now(timezone.utc) - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0)
        day_end = day_start + timedelta(days=1)
        count = PostQueue.query.filter(
            PostQueue.status == "posted",
            PostQueue.posted_at >= day_start,
            PostQueue.posted_at < day_end,
        ).count()
        weekly_data.append({"day": day.strftime("%d/%m"), "count": count})

    # Posts recentes (últimos 20)
    recent_posts = (
        PostQueue.query.order_by(PostQueue.created_at.desc()).limit(20).all()
    )

    # Mapeamento client_id → client para exibir nome
    client_map = {c.id: c for c in clients}

    # Contas Instagram
    accounts = InstagramAccount.query.all()

    return render_template(
        "admin.html",
        clients=clients,
        total_posts=total_posts,
        posted=posted,
        pending=pending,
        failed=failed,
        drafts=drafts,
        posted_today=posted_today,
        weekly_data=weekly_data,
        recent_posts=recent_posts,
        client_map=client_map,
        accounts=accounts,
    )


@admin_bp.route("/client/<int:client_id>/toggle-plan", methods=["POST"])
@admin_required
def toggle_plan(client_id):
    client = db.session.get(Client, client_id)
    if client:
        client.plan = "pro" if client.plan == "free" else "free"
        db.session.commit()
        flash(f"{client.name} agora é {client.plan.upper()}.", "success")
    return redirect(url_for("admin.index"))


@admin_bp.route("/client/<int:client_id>/toggle-admin", methods=["POST"])
@admin_required
def toggle_admin(client_id):
    client = db.session.get(Client, client_id)
    if client and client.id != current_user.id:
        client.is_admin = not client.is_admin
        db.session.commit()
        flash(f"{client.name} — admin: {client.is_admin}", "success")
    return redirect(url_for("admin.index"))


@admin_bp.route("/post/<int:post_id>/retry", methods=["POST"])
@admin_required
def retry_post(post_id):
    post = db.session.get(PostQueue, post_id)
    if post and post.status == "failed":
        post.status = "pending"
        post.error_message = None
        db.session.commit()
        flash("Post reenviado para a fila.", "success")
    return redirect(url_for("admin.index"))


@admin_bp.route("/post/<int:post_id>/delete", methods=["POST"])
@admin_required
def delete_post(post_id):
    post = db.session.get(PostQueue, post_id)
    if post:
        if os.path.exists(post.image_path):
            os.remove(post.image_path)
        db.session.delete(post)
        db.session.commit()
        flash("Post removido.", "info")
    return redirect(url_for("admin.index"))


@admin_bp.route("/client/<int:client_id>/approve-pro", methods=["POST"])
@admin_required
def approve_pro(client_id):
    """Aprova pagamento PIX e ativa plano Pro."""
    client = db.session.get(Client, client_id)
    if client:
        client.plan = "pro"
        db.session.commit()
        flash(f"{client.name} — Plano PRO ativado!", "success")
    return redirect(url_for("admin.index"))


@admin_bp.route("/client/<int:client_id>/reject-pro", methods=["POST"])
@admin_required
def reject_pro(client_id):
    """Rejeita pagamento — volta para free."""
    client = db.session.get(Client, client_id)
    if client:
        client.plan = "free"
        db.session.commit()
        flash(f"{client.name} — Pagamento rejeitado, voltou para FREE.", "info")
    return redirect(url_for("admin.index"))
