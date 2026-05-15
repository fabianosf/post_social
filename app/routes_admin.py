"""
Painel Administrativo — Gestão completa de usuários, posts e sistema.
Acessível apenas por usuários com is_admin=True.
"""

import os
from datetime import datetime, timezone, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

_BRT = ZoneInfo("America/Sao_Paulo")
from urllib.parse import quote as _urlquote

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
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
    # Busca e filtro
    search = request.args.get("q", "").strip()
    plan_filter = request.args.get("plan", "all")

    query = Client.query
    if search:
        query = query.filter(
            db.or_(
                Client.name.ilike(f"%{search}%"),
                Client.email.ilike(f"%{search}%"),
            )
        )
    if plan_filter != "all":
        query = query.filter_by(plan=plan_filter)

    clients = query.order_by(Client.created_at.desc()).all()

    # Stats globais
    total_clients = Client.query.count()
    pro_clients = Client.query.filter_by(plan="pro").count()
    free_clients = Client.query.filter_by(plan="free").count()
    pending_pro_clients = Client.query.filter_by(plan="pending_pro").count()

    total_posts = PostQueue.query.count()
    posted = PostQueue.query.filter_by(status="posted").count()
    pending = PostQueue.query.filter_by(status="pending").count()
    failed = PostQueue.query.filter_by(status="failed").count()
    drafts = PostQueue.query.filter_by(status="draft").count()

    now_brt = datetime.now(_BRT)
    today_start_utc = now_brt.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    posted_today = PostQueue.query.filter(
        PostQueue.status == "posted",
        PostQueue.posted_at >= today_start_utc,
    ).count()

    # Posts últimos 7 dias
    weekly_data = []
    for i in range(6, -1, -1):
        day_brt = now_brt - timedelta(days=i)
        day_start_utc = day_brt.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
        day_end_utc = (day_brt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
        count = PostQueue.query.filter(
            PostQueue.status == "posted",
            PostQueue.posted_at >= day_start_utc,
            PostQueue.posted_at < day_end_utc,
        ).count()
        weekly_data.append({"day": day_brt.strftime("%d/%m"), "count": count})

    # Posts recentes
    recent_posts = PostQueue.query.order_by(PostQueue.created_at.desc()).limit(20).all()

    # Mapeamento para exibição
    all_clients = Client.query.all()
    client_map = {c.id: c for c in all_clients}
    accounts = InstagramAccount.query.all()

    # Último post por cliente
    last_post_by_client = {}
    for c in all_clients:
        lp = PostQueue.query.filter_by(client_id=c.id).order_by(PostQueue.created_at.desc()).first()
        last_post_by_client[c.id] = lp

    return render_template(
        "admin.html",
        clients=clients,
        total_clients=total_clients,
        pro_clients=pro_clients,
        free_clients=free_clients,
        pending_pro_clients=pending_pro_clients,
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
        last_post_by_client=last_post_by_client,
        search=search,
        plan_filter=plan_filter,
    )


# ── Gestão de planos ──────────────────────────────

@admin_bp.route("/client/<int:client_id>/set-plan", methods=["POST"])
@admin_required
def set_plan(client_id):
    client = db.session.get(Client, client_id)
    plan = request.form.get("plan", "free")
    if client and plan in ("free", "pro", "pending_pro"):
        client.plan = plan
        db.session.commit()
        flash(f"{client.name} → plano {plan.upper()} definido.", "success")
    return redirect(url_for("admin.index") + _keep_filters())


@admin_bp.route("/client/<int:client_id>/toggle-plan", methods=["POST"])
@admin_required
def toggle_plan(client_id):
    client = db.session.get(Client, client_id)
    if client:
        client.plan = "pro" if client.plan in ("free", "pending_pro") else "free"
        db.session.commit()
        flash(f"{client.name} agora é {client.plan.upper()}.", "success")
    return redirect(url_for("admin.index") + _keep_filters())


@admin_bp.route("/client/<int:client_id>/approve-pro", methods=["POST"])
@admin_required
def approve_pro(client_id):
    client = db.session.get(Client, client_id)
    if client:
        client.plan = "pro"
        client.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        db.session.commit()
        flash(f"{client.name} — Plano PRO ativado!", "success")
    return redirect(url_for("admin.index"))


@admin_bp.route("/client/<int:client_id>/reject-pro", methods=["POST"])
@admin_required
def reject_pro(client_id):
    client = db.session.get(Client, client_id)
    if client:
        client.plan = "free"
        db.session.commit()
        flash(f"{client.name} — Pagamento rejeitado, voltou para FREE.", "info")
    return redirect(url_for("admin.index"))


# ── Bloquear / desbloquear cliente ───────────────

@admin_bp.route("/client/<int:client_id>/toggle-block", methods=["POST"])
@admin_required
def toggle_block(client_id):
    if client_id == current_user.id:
        flash("Você não pode bloquear sua própria conta.", "error")
        return redirect(url_for("admin.index") + _keep_filters())
    client = db.session.get(Client, client_id)
    if client:
        client.is_blocked = not client.is_blocked
        db.session.commit()
        status = "bloqueado" if client.is_blocked else "desbloqueado"
        flash(f"{client.name} foi {status}.", "info")
    return redirect(url_for("admin.index") + _keep_filters())


# ── Gestão de admins ──────────────────────────────

@admin_bp.route("/client/<int:client_id>/toggle-admin", methods=["POST"])
@admin_required
def toggle_admin(client_id):
    client = db.session.get(Client, client_id)
    if client and client.id != current_user.id:
        client.is_admin = not client.is_admin
        db.session.commit()
        flash(f"{client.name} — admin: {client.is_admin}", "success")
    return redirect(url_for("admin.index") + _keep_filters())


# ── Criar usuário ─────────────────────────────────

@admin_bp.route("/clients/create", methods=["POST"])
@admin_required
def create_client():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    plan = request.form.get("plan", "free")
    is_admin = request.form.get("is_admin") == "on"

    if not name or not email or not password:
        flash("Preencha nome, email e senha.", "error")
        return redirect(url_for("admin.index"))

    if len(password) < 6:
        flash("Senha deve ter pelo menos 6 caracteres.", "error")
        return redirect(url_for("admin.index"))

    if Client.query.filter_by(email=email).first():
        flash(f"Email {email} já está cadastrado.", "error")
        return redirect(url_for("admin.index"))

    client = Client(name=name, email=email, plan=plan, is_admin=is_admin)
    client.set_password(password)
    db.session.add(client)
    db.session.commit()
    flash(f"Usuário {name} criado com sucesso!", "success")
    return redirect(url_for("admin.index"))


# ── Editar usuário ────────────────────────────────

@admin_bp.route("/client/<int:client_id>/edit", methods=["POST"])
@admin_required
def edit_client(client_id):
    client = db.session.get(Client, client_id)
    if not client:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin.index"))

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()

    if name:
        client.name = name
    if email and email != client.email:
        if Client.query.filter_by(email=email).first():
            flash(f"Email {email} já está em uso.", "error")
            return redirect(url_for("admin.index") + _keep_filters())
        client.email = email

    db.session.commit()
    flash(f"Dados de {client.name} atualizados.", "success")
    return redirect(url_for("admin.index") + _keep_filters())


# ── Resetar senha ─────────────────────────────────

@admin_bp.route("/client/<int:client_id>/reset-password", methods=["POST"])
@admin_required
def reset_password(client_id):
    client = db.session.get(Client, client_id)
    if not client:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin.index"))

    new_password = request.form.get("new_password", "").strip()
    if len(new_password) < 6:
        flash("Nova senha deve ter pelo menos 6 caracteres.", "error")
        return redirect(url_for("admin.index") + _keep_filters())

    client.set_password(new_password)
    db.session.commit()
    flash(f"Senha de {client.name} redefinida.", "success")
    return redirect(url_for("admin.index") + _keep_filters())


# ── Excluir usuário ───────────────────────────────

@admin_bp.route("/client/<int:client_id>/delete", methods=["POST"])
@admin_required
def delete_client(client_id):
    if client_id == current_user.id:
        flash("Você não pode excluir sua própria conta.", "error")
        return redirect(url_for("admin.index"))

    client = db.session.get(Client, client_id)
    if client:
        # Remover arquivos de upload
        for post in client.posts:
            for path in post.image_path.split("|"):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

        db.session.delete(client)
        db.session.commit()
        flash(f"Usuário {client.name} excluído.", "info")
    return redirect(url_for("admin.index") + _keep_filters())


# ── Gestão de posts ───────────────────────────────

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
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        db.session.delete(post)
        db.session.commit()
        flash("Post removido.", "info")
    return redirect(url_for("admin.index"))


# ── API status rápido ─────────────────────────────

@admin_bp.route("/api/stats")
@admin_required
def api_stats():
    return jsonify({
        "clients": Client.query.count(),
        "pro": Client.query.filter_by(plan="pro").count(),
        "pending_pro": Client.query.filter_by(plan="pending_pro").count(),
        "posts_today": PostQueue.query.filter(
            PostQueue.status == "posted",
            PostQueue.posted_at >= datetime.now(_BRT).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None),
        ).count(),
        "failed": PostQueue.query.filter_by(status="failed").count(),
    })


# ── Instagram Challenge Resolution ────────────────

@admin_bp.route("/ig-challenge/<int:account_id>", methods=["GET"])
@admin_required
def ig_challenge_page(account_id):
    """Página para resolver verificação do Instagram."""
    from pathlib import Path
    import json
    account = InstagramAccount.query.get_or_404(account_id)
    challenge_url = ""
    challenge_file = Path("sessions") / f"challenge_{account.id}.json"
    if challenge_file.exists():
        try:
            data = json.loads(challenge_file.read_text())
            challenge_url = data.get("challenge_url", "")
        except Exception:
            pass
    return render_template("ig_challenge.html", account=account, challenge_url=challenge_url)


@admin_bp.route("/ig-challenge/<int:account_id>/send", methods=["POST"])
@admin_required
def ig_challenge_send(account_id):
    """Obtém a URL do challenge para abrir no navegador."""
    account = InstagramAccount.query.get_or_404(account_id)

    from instagrapi import Client
    from instagrapi.exceptions import ChallengeRequired
    from pathlib import Path
    import json

    cl = Client()
    cl.delay_range = [2, 5]
    password = account.get_ig_password()

    try:
        cl.login(account.ig_username, password)
        session_file = Path("sessions") / f"account_{account.id}.json"
        cl.dump_settings(session_file)
        account.status = "active"
        account.status_message = None
        db.session.commit()
        flash(f"@{account.ig_username} conectado!", "success")
        return redirect(url_for("admin.index"))
    except ChallengeRequired:
        last = cl.last_json
    except Exception as e:
        flash(f"Erro: {e}", "error")
        return redirect(url_for("admin.ig_challenge_page", account_id=account_id))

    challenge_url = last.get("challenge", {}).get("url", "")
    # Salvar URL para mostrar na página
    challenge_file = Path("sessions") / f"challenge_{account.id}.json"
    with open(challenge_file, "w") as f:
        json.dump({"challenge_url": challenge_url}, f)

    return redirect(url_for("admin.ig_challenge_page", account_id=account_id))


@admin_bp.route("/ig-challenge/<int:account_id>/verify", methods=["POST"])
@admin_required
def ig_challenge_verify(account_id):
    """Tenta login novamente após verificação no navegador."""
    account = InstagramAccount.query.get_or_404(account_id)

    from instagrapi import Client
    from instagrapi.exceptions import ChallengeRequired
    from pathlib import Path

    cl = Client()
    cl.delay_range = [2, 5]
    password = account.get_ig_password()

    try:
        cl.login(account.ig_username, password)
        session_file = Path("sessions") / f"account_{account.id}.json"
        cl.dump_settings(session_file)
        challenge_file = Path("sessions") / f"challenge_{account.id}.json"
        challenge_file.unlink(missing_ok=True)
        account.status = "active"
        account.status_message = None
        db.session.commit()
        flash(f"@{account.ig_username} conectado com sucesso!", "success")
        return redirect(url_for("admin.index"))
    except ChallengeRequired:
        flash("Instagram ainda exige verificação. Complete o link no navegador e tente novamente.", "error")
    except Exception as e:
        flash(f"Erro: {e}", "error")

    return redirect(url_for("admin.ig_challenge_page", account_id=account_id))


# ── Helper ────────────────────────────────────────

def _keep_filters():
    q = request.form.get("q") or request.args.get("q", "")
    plan = request.form.get("plan_filter") or request.args.get("plan", "all")
    params = []
    if q:
        params.append(f"q={_urlquote(q)}")
    if plan and plan != "all":
        params.append(f"plan={_urlquote(plan)}")
    return ("?" + "&".join(params)) if params else ""
