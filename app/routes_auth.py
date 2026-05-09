"""
Rotas de autenticação: cadastro e login do cliente.
"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required

from .models import db, Client, InstagramAccount

auth_bp = Blueprint("auth", __name__)

# In-memory brute-force protection: {ip: {"count": int, "locked_until": datetime|None}}
_login_attempts: dict = defaultdict(lambda: {"count": 0, "locked_until": None})
_MAX_ATTEMPTS = 10
_LOCKOUT_MINUTES = 15


@auth_bp.route("/cadastro", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Preencha todos os campos.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("A senha deve ter pelo menos 6 caracteres.", "error")
            return render_template("register.html")

        if Client.query.filter_by(email=email).first():
            flash("Email já cadastrado.", "error")
            return render_template("register.html")

        client = Client(name=name, email=email)
        client.set_password(password)
        # Trial de 3 dias Pro gratuito
        client.plan = "pro"
        client.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=3)
        db.session.add(client)
        db.session.commit()

        login_user(client)
        flash(f"Bem-vindo, {name}!", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        record = _login_attempts[ip]
        now = datetime.now(timezone.utc)

        # Check temporary lockout
        if record["locked_until"] and now < record["locked_until"]:
            remaining = int((record["locked_until"] - now).total_seconds() / 60) + 1
            flash(f"Muitas tentativas. Tente novamente em {remaining} minuto(s).", "error")
            return render_template("login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        client = Client.query.filter_by(email=email).first()

        if not client or not client.check_password(password):
            record["count"] += 1
            if record["count"] >= _MAX_ATTEMPTS:
                record["locked_until"] = now + timedelta(minutes=_LOCKOUT_MINUTES)
                record["count"] = 0
                flash(f"Conta bloqueada temporariamente por {_LOCKOUT_MINUTES} minutos.", "error")
            else:
                flash("Email ou senha incorretos.", "error")
            return render_template("login.html")

        if client.is_blocked:
            flash("Sua conta foi suspensa. Entre em contato com o suporte.", "error")
            return render_template("login.html")

        # Reset on successful login
        record["count"] = 0
        record["locked_until"] = None

        login_user(client)

        # Auto-selecionar conta Instagram ao logar
        active_accounts = InstagramAccount.query.filter_by(client_id=client.id).all()
        if len(active_accounts) == 1:
            session["active_account_id"] = active_accounts[0].id
            if client.default_account_id != active_accounts[0].id:
                client.default_account_id = active_accounts[0].id
                db.session.commit()
        elif len(active_accounts) > 1:
            if client.default_account_id:
                session["active_account_id"] = client.default_account_id
            else:
                return redirect(url_for("dashboard.select_account"))

        return redirect(url_for("dashboard.index"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu da conta.", "info")
    return redirect(url_for("auth.login"))
