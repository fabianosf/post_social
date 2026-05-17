"""
Rotas de contas Instagram: conectar, desconectar, configurar slots.
"""

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import flash, redirect, request, url_for, session, jsonify, current_app
from flask_login import login_required, current_user

from ..models import db, InstagramAccount, PostQueue
from . import dashboard_bp


@dashboard_bp.route("/instagram/oauth/start")
@login_required
def instagram_oauth_start():
    """Redireciona para login Meta (Facebook) — Instagram Profissional vinculado à Página."""
    app_id = os.environ.get("META_APP_ID", "").strip()
    secret = os.environ.get("META_APP_SECRET", "").strip()
    if not app_id or not secret:
        flash(
            "Conexão oficial Meta não está configurada no servidor (META_APP_ID / META_APP_SECRET).",
            "error",
        )
        return redirect(url_for("dashboard.index"))

    state = secrets.token_urlsafe(32)
    session["instagram_oauth_state"] = state

    from modules.instagram_graph import oauth_authorize_url

    return redirect(oauth_authorize_url(state))


@dashboard_bp.route("/instagram/oauth/callback")
@login_required
def instagram_oauth_callback():
    from modules import instagram_graph as ig_graph

    err = request.args.get("error")
    if err:
        desc = request.args.get("error_description") or err
        flash(f"Meta: {desc[:300]}", "error")
        return redirect(url_for("dashboard.index"))

    if request.args.get("state") != session.get("instagram_oauth_state"):
        flash("Sessão de autorização inválida ou expirada. Tente conectar novamente.", "error")
        return redirect(url_for("dashboard.index"))
    session.pop("instagram_oauth_state", None)

    code = request.args.get("code", "").strip()
    if not code:
        flash("Resposta Meta sem código de autorização.", "error")
        return redirect(url_for("dashboard.index"))

    try:
        short = ig_graph.exchange_code_for_short_user_token(code)
        long_user = ig_graph.exchange_for_long_lived_user_token(short)
        pages = ig_graph.list_pages_with_instagram(long_user)
    except Exception as e:
        flash(f"Não foi possível completar a conexão com Meta: {str(e)[:280]}", "error")
        return redirect(url_for("dashboard.index"))

    if not pages:
        flash(
            "Nenhuma Página do Facebook com Instagram profissional encontrada. "
            "Use um perfil Instagram Creator ou Business vinculado a uma Página.",
            "error",
        )
        return redirect(url_for("dashboard.index"))

    p0 = pages[0]
    ig_username = p0["ig_username"]
    share_fb = True

    existing_count = InstagramAccount.query.filter_by(client_id=current_user.id).count()
    existing = InstagramAccount.query.filter_by(
        client_id=current_user.id, ig_username=ig_username
    ).first()
    if existing_count >= current_user.max_accounts() and not existing:
        flash("Limite de contas do seu plano atingido.", "error")
        return redirect(url_for("dashboard.index"))

    if existing:
        acc = existing
    else:
        acc = InstagramAccount(
            client_id=current_user.id,
            ig_username=ig_username,
            share_to_facebook=share_fb,
            label=ig_username,
        )
        db.session.add(acc)
        db.session.flush()

    acc.set_ig_password(p0["page_access_token"])
    acc.ig_graph_user_id = p0["ig_user_id"]
    acc.ig_graph_page_id = p0["page_id"]
    acc.ig_connection_type = "graph_oauth"
    acc.share_to_facebook = share_fb
    acc.status = "active"
    acc.status_message = None
    acc.last_login_at = datetime.now(timezone.utc)

    old_sess = Path(current_app.config["UPLOAD_FOLDER"]).parent / "sessions" / f"account_{acc.id}.json"
    old_sess.unlink(missing_ok=True)

    db.session.commit()

    if len(pages) > 1:
        flash(
            f"@{ig_username} conectado via Meta. "
            f"(Várias páginas encontradas — usamos: {p0.get('page_name') or p0['page_id']})",
            "success",
        )
    else:
        flash(f"@{ig_username} conectado com sucesso via Meta (login oficial).", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/selecionar-conta", methods=["GET", "POST"])
@login_required
def select_account():
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()
    if not accounts:
        return redirect(url_for("dashboard.index"))
    if len(accounts) == 1:
        session["active_account_id"] = accounts[0].id
        current_user.default_account_id = accounts[0].id
        db.session.commit()
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        acc_id = request.form.get("account_id", type=int)
        acc = next((a for a in accounts if a.id == acc_id), None)
        if acc:
            session["active_account_id"] = acc.id
            current_user.default_account_id = acc.id
            db.session.commit()
            flash(f"Conta @{acc.ig_username} selecionada como padrão.", "success")
        return redirect(url_for("dashboard.index"))
    from flask import render_template
    return render_template("select_account.html", accounts=accounts)


@dashboard_bp.route("/api/set-active-account", methods=["POST"])
@login_required
def set_active_account():
    if request.is_json:
        acc_id = (request.get_json(silent=True) or {}).get("account_id")
    else:
        acc_id = request.form.get("account_id", type=int)
    acc = InstagramAccount.query.filter_by(id=acc_id, client_id=current_user.id).first()
    if acc:
        session["active_account_id"] = acc.id
        current_user.default_account_id = acc.id
        db.session.commit()
        return jsonify({"ok": True, "username": acc.ig_username})
    return jsonify({"ok": False}), 400


@dashboard_bp.route("/instagram/connect", methods=["POST"])
@login_required
def connect_instagram():
    ig_username = request.form.get("ig_username", "").strip().lstrip("@")
    ig_password = request.form.get("ig_password", "")
    share_fb = request.form.get("share_facebook") == "on"
    label = request.form.get("label", "").strip() or ig_username

    if not ig_username or not ig_password:
        flash("Preencha usuário e senha.", "error")
        return redirect(url_for("dashboard.index"))

    existing_count = InstagramAccount.query.filter_by(client_id=current_user.id).count()
    if existing_count >= current_user.max_accounts():
        already = InstagramAccount.query.filter_by(
            client_id=current_user.id, ig_username=ig_username
        ).first()
        if not already:
            flash(
                "Plano Free permite apenas 1 conta Instagram. "
                "Faça upgrade para o Plano Pro para adicionar mais contas.",
                "error",
            )
            return redirect(url_for("dashboard.index"))

    existing = InstagramAccount.query.filter_by(
        client_id=current_user.id, ig_username=ig_username
    ).first()

    if existing:
        existing.set_ig_password(ig_password)
        existing.share_to_facebook = share_fb
        existing.label = label
        existing.status = "active"
        existing.status_message = None
        existing.ig_connection_type = "password"
        existing.ig_graph_user_id = None
        existing.ig_graph_page_id = None
    else:
        account = InstagramAccount(
            client_id=current_user.id,
            ig_username=ig_username,
            share_to_facebook=share_fb,
            label=label,
            status="active",
            ig_connection_type="password",
        )
        account.set_ig_password(ig_password)
        db.session.add(account)

    db.session.commit()
    flash(f"@{ig_username} conectado com sucesso!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/instagram/connect-session", methods=["POST"])
@login_required
def connect_instagram_session():
    session_id = request.form.get("session_id", "").strip()
    share_fb = request.form.get("share_facebook") == "on"

    if not session_id:
        flash("Cole o Session ID do Instagram.", "error")
        return redirect(url_for("dashboard.index"))

    existing_count = InstagramAccount.query.filter_by(client_id=current_user.id).count()
    if existing_count >= current_user.max_accounts():
        flash("Plano Free permite apenas 1 conta. Faça upgrade para Pro.", "error")
        return redirect(url_for("dashboard.index"))

    from instagrapi import Client

    cl = Client()
    cl.delay_range = [2, 5]

    try:
        cl.login_by_sessionid(session_id)
        ig_username = cl.account_info().username
    except Exception as e:
        flash(f"Session ID inválido ou expirado: {e}", "error")
        return redirect(url_for("dashboard.index"))

    existing = InstagramAccount.query.filter_by(
        client_id=current_user.id, ig_username=ig_username
    ).first()

    if existing:
        existing.share_to_facebook = share_fb
        existing.status = "active"
        existing.status_message = None
        existing.ig_connection_type = "session"
        existing.ig_graph_user_id = None
        existing.ig_graph_page_id = None
        account = existing
    else:
        account = InstagramAccount(
            client_id=current_user.id,
            ig_username=ig_username,
            share_to_facebook=share_fb,
            label=ig_username,
            ig_connection_type="session",
        )
        account.set_ig_password(session_id)
        db.session.add(account)

    db.session.commit()

    session_file = Path(current_app.root_path).parent / "sessions" / f"account_{account.id}.json"
    cl.dump_settings(str(session_file))

    flash(f"@{ig_username} conectado via Session ID!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/instagram/<int:account_id>/disconnect", methods=["POST"])
@login_required
def disconnect_instagram(account_id):
    account = InstagramAccount.query.filter_by(id=account_id, client_id=current_user.id).first()
    if account:
        try:
            PostQueue.query.filter_by(account_id=account.id).update({"account_id": None})
            db.session.delete(account)
            db.session.commit()
            flash("Conta desconectada.", "info")
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao desconectar conta: {e}", "error")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/api/account-slots")
@login_required
def get_account_slots():
    account_id = request.args.get("account_id", type=int)
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()
    if account_id:
        account = next((a for a in accounts if a.id == account_id), None)
    else:
        account = accounts[0] if accounts else None
    if not account:
        return jsonify({"weekday_slots": ["09:00", "17:00"], "weekend_slots": ["10:30", "16:00"]})
    try:
        wd = json.loads(account.weekday_slots or "[]") or ["09:00", "17:00"]
    except Exception:
        wd = ["09:00", "17:00"]
    try:
        we = json.loads(account.weekend_slots or "[]") or ["10:30", "16:00"]
    except Exception:
        we = ["10:30", "16:00"]
    return jsonify({"weekday_slots": wd, "weekend_slots": we})


@dashboard_bp.route("/api/schedule-slots", methods=["POST"])
@login_required
def save_schedule_slots():
    data = request.get_json()
    account_id = data.get("account_id")
    weekday = data.get("weekday_slots", [])
    weekend = data.get("weekend_slots", [])

    account = InstagramAccount.query.filter_by(id=account_id, client_id=current_user.id).first()
    if not account:
        return jsonify({"error": "Conta não encontrada"}), 404

    pattern = re.compile(r"^\d{2}:\d{2}$")
    weekday = [s for s in weekday if pattern.match(s)][:2]
    weekend = [s for s in weekend if pattern.match(s)][:2]

    account.weekday_slots = json.dumps(weekday if weekday else ["09:00", "17:00"])
    account.weekend_slots = json.dumps(weekend if weekend else ["10:30", "16:00"])
    db.session.commit()
    return jsonify({"ok": True})
