"""
Relatório semanal por email — Envia resumo de atividade para cada cliente.
Rodar via cron: python -m modules.weekly_report
"""

import os
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv

load_dotenv()


def send_weekly_reports():
    from app import create_app
    from app.models import db, Client, PostQueue, InstagramAccount

    app = create_app()

    with app.app_context():
        smtp_host = os.environ.get("SMTP_HOST")
        smtp_user = os.environ.get("SMTP_USER")
        smtp_pass = os.environ.get("SMTP_PASS")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))

        if not smtp_host or not smtp_user:
            print("SMTP não configurado. Abortando.")
            return

        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        clients = Client.query.filter_by(notify_email=True).all()

        for client in clients:
            # Stats da semana
            posted = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= week_ago,
            ).count()

            failed = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "failed",
                PostQueue.created_at >= week_ago,
            ).count()

            pending = PostQueue.query.filter_by(
                client_id=client.id, status="pending"
            ).count()

            scheduled = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "pending",
                PostQueue.scheduled_at.isnot(None),
            ).count()

            accounts = InstagramAccount.query.filter_by(client_id=client.id).all()

            # Alertas de sessão
            session_alerts = []
            for acc in accounts:
                if acc.last_login_at:
                    days = (datetime.now(timezone.utc) - acc.last_login_at).days
                    if days > 80:
                        session_alerts.append(f"@{acc.ig_username} ({days} dias sem renovar)")

            if posted == 0 and failed == 0 and pending == 0:
                continue

            # Montar email
            html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 2rem;">
                <div style="max-width: 500px; margin: 0 auto; background: #1a1a2e; border-radius: 12px; padding: 2rem; border: 1px solid #2a2a4a;">
                    <h1 style="color: #7c5cff; font-size: 1.5rem; margin-bottom: 1rem;">PostSocial — Resumo Semanal</h1>
                    <p style="color: #ccc;">Olá, {client.name}! Aqui está o resumo da sua semana:</p>

                    <table style="width: 100%; margin: 1.5rem 0; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 0.5rem; color: #4ade80; font-size: 1.5rem; font-weight: bold; text-align: center;">{posted}</td>
                            <td style="padding: 0.5rem; color: #f87171; font-size: 1.5rem; font-weight: bold; text-align: center;">{failed}</td>
                            <td style="padding: 0.5rem; color: #60a5fa; font-size: 1.5rem; font-weight: bold; text-align: center;">{pending}</td>
                            <td style="padding: 0.5rem; color: #fbbf24; font-size: 1.5rem; font-weight: bold; text-align: center;">{scheduled}</td>
                        </tr>
                        <tr>
                            <td style="padding: 0.3rem; color: #888; font-size: 0.8rem; text-align: center;">Postados</td>
                            <td style="padding: 0.3rem; color: #888; font-size: 0.8rem; text-align: center;">Erros</td>
                            <td style="padding: 0.3rem; color: #888; font-size: 0.8rem; text-align: center;">Na Fila</td>
                            <td style="padding: 0.3rem; color: #888; font-size: 0.8rem; text-align: center;">Agendados</td>
                        </tr>
                    </table>

                    <p style="color: #aaa; font-size: 0.85rem;">Plano: <strong style="color: #7c5cff;">{client.plan.upper()}</strong> — {client.posts_this_month or 0} posts este mês</p>
            """

            if session_alerts:
                html += '<div style="background: #3a1a1a; border: 1px solid #5a2a2a; border-radius: 8px; padding: 1rem; margin-top: 1rem;">'
                html += '<p style="color: #f87171; font-weight: bold; margin-bottom: 0.5rem;">⚠ Alertas de Sessão:</p>'
                for alert in session_alerts:
                    html += f'<p style="color: #ccc; font-size: 0.85rem;">{alert}</p>'
                html += '</div>'

            html += """
                    <p style="color: #666; font-size: 0.8rem; margin-top: 1.5rem; text-align: center;">PostSocial — Automação inteligente para Instagram</p>
                </div>
            </body>
            </html>
            """

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"PostSocial — Seu resumo semanal ({posted} posts)"
            msg["From"] = smtp_user
            msg["To"] = client.email
            msg.attach(MIMEText(html, "html"))

            try:
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                print(f"Relatório enviado para {client.email}")
            except Exception as e:
                print(f"Erro ao enviar para {client.email}: {e}")


if __name__ == "__main__":
    send_weekly_reports()
