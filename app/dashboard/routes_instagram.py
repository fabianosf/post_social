"""
Rotas de contas Instagram: conectar, desconectar, configurar slots.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import flash, redirect, request, url_for, session, jsonify, current_app
from flask_login import login_required, current_user

from ..models import db, InstagramAccount
from . import dashboard_bp


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

    try:
        from instagrapi import Client as _IGClient
        _cl = _IGClient()
        _cl.delay_range = [1, 3]
        _session_path = Path(current_app.config["UPLOAD_FOLDER"]).parent / "sessions" / f"test_{current_user.id}.json"
        _cl.login(ig_username, ig_password)
        _cl.dump_settings(_session_path)
    except Exception as _e:
        err = str(_e)
        if "bad_password" in err.lower() or "incorrect" in err.lower():
            flash("Senha incorreta. Verifique e tente novamente.", "error")
        elif "challenge" in err.lower():
            flash("Instagram pediu verificação. Confirme no app do celular e tente novamente.", "error")
        elif "two_factor" in err.lower() or "2fa" in err.lower():
            flash("2FA ativo. Desative o 2FA no Instagram ou use um Session ID.", "error")
        elif "not found" in err.lower() or "can't find" in err.lower():
            flash(f"Usuário @{ig_username} não encontrado no Instagram. Verifique o nome de usuário.", "error")
        else:
            flash(f"Não foi possível conectar: {err[:120]}", "error")
        return redirect(url_for("dashboard.index"))

    if existing:
        existing.set_ig_password(ig_password)
        existing.share_to_facebook = share_fb
        existing.label = label
        existing.status = "active"
        existing.status_message = None
        existing.last_login_at = datetime.now(timezone.utc)
        session_file = Path(current_app.config["UPLOAD_FOLDER"]).parent / "sessions" / f"account_{existing.id}.json"
        _session_path.rename(session_file)
    else:
        account = InstagramAccount(
            client_id=current_user.id,
            ig_username=ig_username,
            share_to_facebook=share_fb,
            label=label,
            status="active",
            last_login_at=datetime.now(timezone.utc),
        )
        account.set_ig_password(ig_password)
        db.session.add(account)
        db.session.flush()
        session_file = Path(current_app.config["UPLOAD_FOLDER"]).parent / "sessions" / f"account_{account.id}.json"
        _session_path.rename(session_file)

    db.session.commit()
    flash(f"@{ig_username} conectado e verificado com sucesso!", "success")
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
        account = existing
    else:
        account = InstagramAccount(
            client_id=current_user.id,
            ig_username=ig_username,
            share_to_facebook=share_fb,
            label=ig_username,
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
        db.session.delete(account)
        db.session.commit()
        flash("Conta desconectada.", "info")
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
