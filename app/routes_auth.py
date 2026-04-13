"""
Rotas de autenticação: cadastro e login do cliente.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required

from .models import db, Client

auth_bp = Blueprint("auth", __name__)


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
        db.session.add(client)
        db.session.commit()

        login_user(client)
        flash(f"Bem-vindo, {name}!", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        client = Client.query.filter_by(email=email).first()

        if not client or not client.check_password(password):
            flash("Email ou senha incorretos.", "error")
            return render_template("login.html")

        if client.is_blocked:
            flash("Sua conta foi suspensa. Entre em contato com o suporte.", "error")
            return render_template("login.html")

        login_user(client)
        return redirect(url_for("dashboard.index"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu da conta.", "info")
    return redirect(url_for("auth.login"))
