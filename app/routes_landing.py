"""
Landing page pública — página de vendas para atrair novos clientes SaaS.
"""

from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user

landing_bp = Blueprint("landing", __name__)


@landing_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("landing.html")
