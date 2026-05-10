"""
Celery task de automação — roda diariamente, gera alertas e checa metas para todos os clientes.
"""

from celery import Task
from celery.utils.log import get_task_logger

from celery_app import celery, make_flask_app

logger = get_task_logger(__name__)

_flask_app = None


def _get_app():
    global _flask_app
    if _flask_app is None:
        _flask_app = make_flask_app()
    return _flask_app


class ContextTask(Task):
    abstract = True

    def __call__(self, *args, **kwargs):
        with _get_app().app_context():
            return self.run(*args, **kwargs)


@celery.task(
    base=ContextTask,
    name="tasks.automation_tasks.run_daily_automation_check",
    queue="postay.maintenance",
    max_retries=1,
)
def run_daily_automation_check():
    """
    Roda diariamente às 9h BRT:
    1. Detecta quedas de engajamento, frequência baixa e posts virais
    2. Persiste alertas novos (sem duplicar alertas do mesmo dia)
    3. Checa metas atingidas
    4. Envia notificações urgentes via email/Telegram
    """
    from datetime import datetime, timezone, timedelta
    from app.models import db, Client, PostQueue, AutomationAlert, GrowthGoal
    from app.automations import generate_smart_alerts, check_goal_progress

    clients = Client.query.filter_by(is_blocked=False).all()
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_60 = datetime.now(timezone.utc) - timedelta(days=60)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    total_alerts = 0
    total_goals_checked = 0
    errors = 0

    for client in clients:
        try:
            posts_30 = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= cutoff_30,
            ).all()

            posts_prev = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= cutoff_60,
                PostQueue.posted_at < cutoff_30,
            ).all()

            # Gera alertas
            alerts = generate_smart_alerts(posts_30, posts_prev)
            urgent = []

            for a in alerts:
                exists = AutomationAlert.query.filter(
                    AutomationAlert.client_id == client.id,
                    AutomationAlert.alert_type == a["alert_type"],
                    AutomationAlert.created_at >= today_start,
                ).first()
                if exists:
                    continue

                row = AutomationAlert(
                    client_id=client.id,
                    alert_type=a["alert_type"],
                    severity=a.get("severity", "info"),
                    title=a["title"],
                    message=a["message"],
                    action=a.get("action"),
                    action_url=a.get("action_url"),
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                )
                db.session.add(row)
                total_alerts += 1

                if a.get("severity") == "error":
                    urgent.append(a)

            db.session.commit()

            # Checa metas atingidas
            goals = GrowthGoal.query.filter_by(client_id=client.id, is_active=True).all()
            for goal in goals:
                prog = check_goal_progress(goal.goal_type, goal.target_value, goal.deadline, posts_30)
                total_goals_checked += 1

                if prog["is_achieved"] and not goal.achieved_at:
                    goal.achieved_at = datetime.now(timezone.utc)
                    db.session.add(AutomationAlert(
                        client_id=client.id,
                        alert_type="goal_achieved",
                        severity="success",
                        title=f"Meta atingida: {goal.label}!",
                        message=f"Parabéns! Você atingiu {prog['current_value']:.0f} de {goal.target_value:.0f} ({prog['progress_pct']:.0f}%).",
                        action="Ver Automações",
                        action_url="/automations",
                        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                    ))
                    urgent.append({"title": f"Meta atingida: {goal.label}!", "severity": "success"})
                    db.session.commit()

                elif not prog["on_track"] and prog["days_remaining"] is not None and prog["days_remaining"] < 7:
                    exists = AutomationAlert.query.filter(
                        AutomationAlert.client_id == client.id,
                        AutomationAlert.alert_type == "goal_at_risk",
                        AutomationAlert.created_at >= today_start,
                    ).first()
                    if not exists:
                        db.session.add(AutomationAlert(
                            client_id=client.id,
                            alert_type="goal_at_risk",
                            severity="warning",
                            title=f"Meta em risco: {goal.label}",
                            message=f"Faltam {prog['days_remaining']} dias e você está em {prog['progress_pct']:.0f}%. Intensifique o ritmo.",
                            action="Ver Metas",
                            action_url="/automations",
                            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                        ))
                        db.session.commit()

            # Envia notificações urgentes
            if urgent and (client.notify_email or client.telegram_chat_id):
                _send_notifications(client, urgent)

        except Exception as e:
            errors += 1
            logger.warning(f"Cliente #{client.id}: {e}")
            try:
                db.session.rollback()
            except Exception:
                pass

    logger.info(
        f"run_daily_automation_check: {total_alerts} alertas criados, "
        f"{total_goals_checked} metas checadas, {errors} erros."
    )
    return {"alerts": total_alerts, "goals": total_goals_checked, "errors": errors}


def _send_notifications(client, urgent_alerts: list):
    """Envia alertas urgentes por email e/ou Telegram."""
    try:
        titles = [a["title"] for a in urgent_alerts]
        summary = f"Postay — {len(titles)} alerta(s): " + " | ".join(titles[:3])

        if client.notify_email:
            _try_send_email(client.email, client.name, summary, urgent_alerts)

        if client.telegram_bot_token and client.telegram_chat_id:
            _try_send_telegram(client.telegram_bot_token, client.telegram_chat_id, urgent_alerts)
    except Exception as e:
        logger.warning(f"Notificação falhou para cliente #{client.id}: {e}")


def _try_send_email(to_email: str, name: str, subject: str, alerts: list):
    import smtplib, os
    from email.mime.text import MIMEText
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    if not all([smtp_host, smtp_user, smtp_pass]):
        return
    body = f"Olá {name},\n\nSeus alertas automáticos do Postay:\n\n"
    for a in alerts:
        body += f"• [{a.get('severity','').upper()}] {a['title']}\n"
        body += f"  {a.get('message', '')}\n\n"
    body += "Acesse https://postay.app/automations para ver todos os alertas.\n\n— Equipe Postay"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_email], msg.as_string())


def _try_send_telegram(token: str, chat_id: str, alerts: list):
    import httpx
    text = "🤖 *Postay — Alertas Automáticos*\n\n"
    icons = {"error": "🔴", "warning": "🟡", "success": "🟢", "info": "🔵"}
    for a in alerts:
        ico = icons.get(a.get("severity", "info"), "•")
        text += f"{ico} *{a['title']}*\n{a.get('message', '')}\n\n"
    text += "Acesse /automations para ver detalhes."
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    httpx.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
