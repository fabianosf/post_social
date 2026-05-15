"""
Postay — Automations Blueprint
Rotas: /automations e /api/automations/*
"""

from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user

from .models import db, PostQueue, AutomationAlert, GrowthGoal
from . import automations as eng

automations_bp = Blueprint("automations", __name__)

_GOAL_TYPE_LABELS = {
    "reach": "Alcance total",
    "likes": "Curtidas totais",
    "posts_week": "Posts por semana",
    "score": "Score médio de engajamento",
}


# ── Helpers ───────────────────────────────────────────────────────

def _posted(days: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return PostQueue.query.filter(
        PostQueue.client_id == current_user.id,
        PostQueue.status == "posted",
        PostQueue.posted_at >= cutoff,
    ).order_by(PostQueue.posted_at.desc()).all()


def _persist_alerts(alerts: list[dict]):
    """Persiste alertas novos, evitando duplicatas do mesmo tipo no mesmo dia."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for a in alerts:
        exists = AutomationAlert.query.filter(
            AutomationAlert.client_id == current_user.id,
            AutomationAlert.alert_type == a["alert_type"],
            AutomationAlert.created_at >= today_start,
        ).first()
        if exists:
            continue
        db.session.add(AutomationAlert(
            client_id=current_user.id,
            alert_type=a["alert_type"],
            severity=a.get("severity", "info"),
            title=a["title"],
            message=a["message"],
            action=a.get("action"),
            action_url=a.get("action_url"),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


# ── Página principal ──────────────────────────────────────────────

@automations_bp.route("/automacoes")
@automations_bp.route("/automations")
@login_required
def index():
    if not current_user.has_pro_features():
        flash("Automações disponíveis nos planos Pro e Agency.", "error")
        return redirect(url_for("payment.index", plan="pro"))
    posts_30 = _posted(30)
    posts_60 = _posted(60)
    posts_prev = [p for p in posts_60 if p not in posts_30]

    # Gera e persiste alertas frescos
    fresh = eng.generate_smart_alerts(posts_30, posts_prev)
    _persist_alerts(fresh)

    # Lê alertas persistidos (não dispensados)
    alerts = AutomationAlert.query.filter_by(
        client_id=current_user.id,
        is_dismissed=False,
    ).order_by(AutomationAlert.created_at.desc()).limit(20).all()

    # Metas com progresso calculado
    goals = GrowthGoal.query.filter_by(client_id=current_user.id, is_active=True).all()
    goal_progress = []
    for g in goals:
        prog = eng.check_goal_progress(g.goal_type, g.target_value, g.deadline, posts_30)
        if prog["is_achieved"] and not g.achieved_at:
            g.achieved_at = datetime.now(timezone.utc)
            db.session.commit()
        goal_progress.append({"goal": g, **prog, "type_label": _GOAL_TYPE_LABELS.get(g.goal_type, g.goal_type)})

    freq = eng.suggest_optimal_frequency(posts_30)
    content = eng.suggest_next_content(posts_30)
    calendar = eng.auto_calendar_suggestions(posts_30, days_ahead=7)

    return render_template(
        "automations.html",
        alerts=alerts,
        alert_count=len([a for a in alerts if a.severity in ("error", "warning")]),
        goal_progress=goal_progress,
        freq=freq,
        content=content,
        calendar=calendar,
        posts_count=len(posts_30),
        goal_type_labels=_GOAL_TYPE_LABELS,
    )


# ── Dispensar alerta ──────────────────────────────────────────────

@automations_bp.route("/api/automations/alerts/<int:alert_id>/dismiss", methods=["POST"])
@login_required
def dismiss_alert(alert_id: int):
    alert = AutomationAlert.query.filter_by(id=alert_id, client_id=current_user.id).first_or_404()
    alert.is_dismissed = True
    db.session.commit()
    return jsonify({"ok": True})


# ── CRUD de metas ─────────────────────────────────────────────────

@automations_bp.route("/api/automations/goals", methods=["POST"])
@login_required
def create_goal():
    body = request.get_json(silent=True) or {}
    goal_type = body.get("goal_type", "").strip()
    label = body.get("label", "").strip()
    target = body.get("target_value")
    period = body.get("period", "monthly")
    deadline_str = body.get("deadline", "")

    if goal_type not in _GOAL_TYPE_LABELS:
        return jsonify({"error": "Tipo de meta inválido"}), 400
    if not target:
        return jsonify({"error": "Valor alvo obrigatório"}), 400

    deadline = None
    if deadline_str:
        try:
            deadline = datetime.fromisoformat(deadline_str).replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({"error": "Data inválida"}), 400

    goal = GrowthGoal(
        client_id=current_user.id,
        goal_type=goal_type,
        label=label or _GOAL_TYPE_LABELS[goal_type],
        target_value=float(target),
        period=period,
        deadline=deadline,
    )
    db.session.add(goal)
    db.session.commit()
    return jsonify({"ok": True, "id": goal.id})


@automations_bp.route("/api/automations/goals/<int:goal_id>", methods=["DELETE"])
@login_required
def delete_goal(goal_id: int):
    goal = GrowthGoal.query.filter_by(id=goal_id, client_id=current_user.id).first_or_404()
    goal.is_active = False
    db.session.commit()
    return jsonify({"ok": True})


# ── API: sugestões frescas (AJAX) ─────────────────────────────────

@automations_bp.route("/api/automations/suggestions")
@login_required
def api_suggestions():
    posts_30 = _posted(30)
    return jsonify({
        "freq": eng.suggest_optimal_frequency(posts_30),
        "content": eng.suggest_next_content(posts_30),
        "calendar": eng.auto_calendar_suggestions(posts_30, days_ahead=7),
    })


# ── API: calendário JSON ──────────────────────────────────────────

@automations_bp.route("/api/automations/calendar")
@login_required
def api_calendar():
    posts_30 = _posted(30)
    return jsonify(eng.auto_calendar_suggestions(posts_30, days_ahead=14))
