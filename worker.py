#!/usr/bin/env python3
"""
PostSocial Worker — Serviço contínuo de postagens.
Suporta: foto, álbum/carrossel, reels/vídeo, agendamento.
Modo: --once (1 ciclo) ou --daemon (loop contínuo a cada 5min)
"""

import os
import random
import smtplib
import sys
import time
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

_BRT = ZoneInfo("America/Sao_Paulo")

from dotenv import load_dotenv

load_dotenv()

from instagrapi import Client as IGClient
from instagrapi.exceptions import (
    LoginRequired, ChallengeRequired, TwoFactorRequired,
    BadPassword, PleaseWaitFewMinutes,
)

from app import create_app
from app.models import db, PostQueue, InstagramAccount, Client, TikTokAccount
from modules.caption_generator import CaptionGenerator
from modules.logger import setup_global_logger
from modules.telegram_notify import notify_post_success, notify_post_failed

BASE_DIR = Path(__file__).parent
SESSION_DIR = BASE_DIR / "sessions"
SESSION_DIR.mkdir(exist_ok=True)

app = create_app()
logger = setup_global_logger(str(BASE_DIR))


_LOGIN_ERROR_COOLDOWN_MINUTES = 30    # Erro genérico: retry após 30 min
_NOT_FOUND_COOLDOWN_MINUTES   = 1440  # Usuário não encontrado: retry após 24h


def get_ig_client(account: InstagramAccount) -> IGClient | None:
    cl = IGClient()
    cl.delay_range = [2, 5]

    session_file = SESSION_DIR / f"account_{account.id}.json"
    username = account.ig_username.lstrip("@")
    password = account.get_ig_password()

    # Cooldown: se login_error recente, não retentar ainda
    if account.status == "login_error" and account.last_login_at:
        last = account.last_login_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
        not_found = "não encontrado" in (account.status_message or "").lower()
        cooldown = _NOT_FOUND_COOLDOWN_MINUTES if not_found else _LOGIN_ERROR_COOLDOWN_MINUTES
        if elapsed < cooldown:
            if not_found:
                logger.warning(f"[@{username}] Usuário não encontrado — aguardando reconexão manual. Pulando.")
            else:
                logger.warning(f"[@{username}] Login error ({elapsed:.0f}min atrás). Cooldown {cooldown}min — pulando.")
            return None

    # Restaurar sessão sem re-autenticar (apenas valida o token salvo)
    if session_file.exists():
        try:
            cl.load_settings(session_file)
            cl.get_timeline_feed()  # valida sem fazer login fresh
            logger.info(f"[@{username}] Sessão restaurada")
            account.status = "active"
            account.status_message = None
            account.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            return cl
        except Exception as e:
            logger.warning(f"[@{username}] Sessão expirada: {e}")
            session_file.unlink(missing_ok=True)

    # Session ID: string longa sem espaços (formato Instagram sessionid)
    _is_session_id = bool(password) and len(password) > 40 and " " not in password

    try:
        if _is_session_id:
            logger.info(f"[@{username}] Re-auth via session_id...")
            cl.login_by_sessionid(password)
        else:
            logger.info(f"[@{username}] Login fresh (usuário/senha)...")
            cl.login(username, password)
        cl.dump_settings(session_file)
        logger.info(f"[@{username}] Login OK")

        account.status = "active"
        account.status_message = None
        account.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        return cl

    except BadPassword:
        logger.error(f"[@{username}] Senha incorreta")
        account.status = "login_error"
        account.status_message = "Senha incorreta. Atualize a senha no painel."
        account.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        return None

    except ChallengeRequired:
        logger.error(f"[@{username}] Challenge required")
        account.status = "challenge_required"
        account.status_message = "Verificação necessária. Faça login pelo app do Instagram no celular e tente novamente."
        account.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        return None

    except TwoFactorRequired:
        logger.error(f"[@{username}] 2FA ativo")
        account.status = "login_error"
        account.status_message = "2FA ativo. Desative o 2FA na conta do Instagram ou use senha de app."
        account.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        return None

    except PleaseWaitFewMinutes:
        logger.error(f"[@{username}] Rate limit")
        account.status_message = "Instagram pediu para aguardar. Tentaremos em breve."
        account.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        return None

    except Exception as e:
        err_str = str(e)
        logger.error(f"[@{username}] Erro: {err_str}")
        account.status = "login_error"
        if _is_session_id:
            account.status_message = "Session ID expirado. Reconecte a conta no painel com um novo Session ID."
        elif "can't find an account" in err_str.lower() or "não encontr" in err_str.lower():
            account.status_message = (
                "Usuário não encontrado. Verifique o nome de usuário e reconecte a conta."
            )
        else:
            account.status_message = "Falha no login. Reconecte a conta no painel."
        account.last_login_at = datetime.now(timezone.utc)
        db.session.commit()
        return None


def generate_caption(post: PostQueue) -> str:
    if post.caption:
        caption = post.caption
    else:
        gen = CaptionGenerator(logger, provider="groq")
        caption = gen.generate(
            image_name=post.image_filename,
            tone="profissional e amigável",
            language="pt-br",
        )

    if post.hashtags:
        caption += f"\n\n{post.hashtags}"

    return caption


def post_photo(cl: IGClient, post: PostQueue, caption: str) -> str | None:
    path = Path(post.image_path)
    if not path.exists():
        return None
    media = cl.photo_upload(path=path, caption=caption)
    return str(media.pk)


def post_album(cl: IGClient, post: PostQueue, caption: str) -> str | None:
    paths = [Path(p) for p in post.image_path.split("|")]
    existing = [p for p in paths if p.exists()]
    if len(existing) < 2:
        return None
    media = cl.album_upload(paths=existing, caption=caption)
    return str(media.pk)


def post_reels(cl: IGClient, post: PostQueue, caption: str) -> str | None:
    path = Path(post.image_path)
    if not path.exists():
        return None
    media = cl.clip_upload(path=path, caption=caption)
    return str(media.pk)


def post_story(cl: IGClient, post: PostQueue, caption: str) -> str | None:
    path = Path(post.image_path)
    if not path.exists():
        return None
    ext = path.suffix.lower()
    if ext in (".mp4", ".mov"):
        media = cl.video_upload_to_story(path=path)
    else:
        media = cl.photo_upload_to_story(path=path)
    return str(media.pk)


def send_email_notification(client: Client, post: PostQueue, success: bool):
    """Envia email de notificação (se configurado)."""
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    if not smtp_host or not smtp_user or not client.notify_email:
        return

    subject = f"PostSocial: {'Postado' if success else 'Erro'} — {post.image_filename}"

    if success:
        body = f"Sua foto '{post.image_filename}' foi postada com sucesso no Instagram!"
    else:
        body = f"Erro ao postar '{post.image_filename}':\n{post.error_message}"

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = client.email

        with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", 587))) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        logger.info(f"Email enviado para {client.email}")
    except Exception as e:
        logger.warning(f"Falha ao enviar email: {e}")


def process_post(post: PostQueue, cl: IGClient, account: InstagramAccount) -> bool:
    # Verificar arquivos
    paths = post.image_path.split("|")
    if not all(os.path.exists(p) for p in paths):
        post.status = "failed"
        post.error_message = "Arquivo(s) não encontrado(s)"
        db.session.commit()
        return False

    caption = generate_caption(post)
    post.caption = caption
    logger.info(f"Post #{post.id} [{post.post_type}] — {caption[:60]}...")

    try:
        uploaders = {
            "photo": post_photo,
            "album": post_album,
            "reels": post_reels,
            "story": post_story,
        }
        uploader = uploaders.get(post.post_type, post_photo)
        media_id = uploader(cl, post, caption)

        if media_id:
            post.instagram_media_id = media_id
            post.status = "posted"
            post.posted_at = datetime.now(timezone.utc)
            post.error_message = None

            # Incrementar contagem mensal
            client = db.session.get(Client, post.client_id)
            if client:
                client.increment_post_count()
                send_email_notification(client, post, success=True)
                notify_post_success(client, post, account)

            db.session.commit()
            logger.info(f"Post #{post.id} — POSTADO Instagram/Facebook! ID: {media_id}")

            # ── TikTok (apenas vídeos/reels) ──────────────────────────
            if getattr(post, "post_to_tiktok", False):
                _try_post_tiktok(post, client)

            return True

        post.status = "failed"
        post.error_message = "Upload retornou vazio"
        client = db.session.get(Client, post.client_id)
        if client:
            notify_post_failed(client, post, account, "Upload retornou vazio")
        db.session.commit()
        return False

    except PleaseWaitFewMinutes:
        post.status = "pending"
        post.error_message = "Rate limit — será tentado novamente"
        db.session.commit()
        return False

    except LoginRequired:
        post.status = "pending"
        post.error_message = "Sessão expirada"
        session_file = SESSION_DIR / f"account_{account.id}.json"
        session_file.unlink(missing_ok=True)
        db.session.commit()
        return False

    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)[:200]}"
        post.retry_count = (post.retry_count or 0) + 1
        MAX_RETRIES = 3
        # Delays: 15min, 30min, 60min
        retry_delays = [15, 30, 60]

        if post.retry_count <= MAX_RETRIES:
            delay = retry_delays[min(post.retry_count - 1, len(retry_delays) - 1)]
            post.status = "pending"
            post.scheduled_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=delay)  # UTC naive, igual ao worker
            post.error_message = f"Tentativa {post.retry_count}/{MAX_RETRIES}: {err_msg}"
            db.session.commit()
            logger.warning(f"Post #{post.id} — Retry {post.retry_count}/{MAX_RETRIES} em {delay}min: {e}")
        else:
            post.status = "failed"
            post.error_message = err_msg
            client = db.session.get(Client, post.client_id)
            if client:
                send_email_notification(client, post, success=False)
                notify_post_failed(client, post, account, f"Falhou após {MAX_RETRIES} tentativas. {err_msg}")
            db.session.commit()
            logger.error(f"Post #{post.id} — FALHA FINAL após {MAX_RETRIES} tentativas: {e}")

        return False


def _try_post_tiktok(post: PostQueue, client: Client):
    """Tenta postar no TikTok se a conta estiver conectada. Suporta foto e vídeo."""
    try:
        from app.routes_tiktok import post_to_tiktok
        tiktok_acc = TikTokAccount.query.filter_by(client_id=post.client_id).first()
        if not tiktok_acc:
            logger.warning(f"Post #{post.id} — TikTok marcado mas nenhuma conta conectada.")
            return
        caption = ((post.caption or "") + " " + (post.hashtags or "")).strip()
        publish_id = post_to_tiktok(tiktok_acc, post)
        logger.info(f"Post #{post.id} — POSTADO TikTok! publish_id: {publish_id}")
        if client:
            from modules.telegram_notify import send_telegram
            send_telegram(client.telegram_bot_token or "", client.telegram_chat_id or "",
                          f"✅ <b>TikTok publicado!</b>\n@{tiktok_acc.username or ''}\n{caption[:80]}")
    except Exception as e:
        logger.error(f"Post #{post.id} — Erro TikTok: {e}")
        if client:
            from modules.telegram_notify import send_telegram
            send_telegram(client.telegram_bot_token or "", client.telegram_chat_id or "",
                          f"❌ <b>Falha no TikTok!</b>\nErro: {str(e)[:200]}")


def _reset_stuck_processing():
    """Posts travados em 'processing' por mais de 15min → volta para pending."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)
    stuck = PostQueue.query.filter(
        PostQueue.status == "processing",
        db.or_(
            PostQueue.scheduled_at.is_(None),
            PostQueue.scheduled_at <= cutoff,
        )
    ).all()
    for post in stuck:
        post.status = "pending"
        post.error_message = "Reset automático: travado em processamento"
        logger.warning(f"Post #{post.id} resetado de 'processing' para 'pending'")
    if stuck:
        db.session.commit()


def _cleanup_old_files():
    """
    Remove arquivos de imagem/vídeo de posts já publicados há mais de 7 dias.
    Mantém o registro no banco para estatísticas.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    old_posts = PostQueue.query.filter(
        PostQueue.status == "posted",
        PostQueue.posted_at <= cutoff,
        PostQueue.image_path.isnot(None),
    ).all()

    cleaned = 0
    for post in old_posts:
        paths = post.image_path.split("|")
        all_removed = True
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    cleaned += 1
                except Exception:
                    all_removed = False
        if all_removed:
            post.image_path = ""  # limpa o caminho após remover

    if cleaned:
        db.session.commit()
        logger.info(f"Limpeza: {cleaned} arquivo(s) de posts antigos removidos.")


def _check_plan_expirations():
    """
    Verifica clientes Pro com plano vencido e rebaixa para Free.
    Notifica via Telegram quando o plano expira.
    """
    now_utc = datetime.now(timezone.utc)
    expired = Client.query.filter(
        Client.plan == "pro",
        Client.is_admin == False,
        Client.plan_expires_at.isnot(None),
        Client.plan_expires_at <= now_utc,
    ).all()

    for client in expired:
        logger.warning(f"Cliente #{client.id} ({client.email}) — plano Pro expirado. Rebaixando para Free.")
        client.plan = "free"
        client.mp_subscription_id = None

        # Notificar via Telegram
        if client.telegram_bot_token and client.telegram_chat_id:
            from modules.telegram_notify import send_telegram
            send_telegram(
                client.telegram_bot_token,
                client.telegram_chat_id,
                "⚠️ <b>Plano Pro expirado</b>\n\n"
                "Seu plano Pro venceu e foi rebaixado para Free.\n"
                "Renove em: <a href='https://captei.shop/pagamento'>captei.shop/pagamento</a>"
            )

    if expired:
        db.session.commit()
        logger.info(f"{len(expired)} plano(s) expirado(s) rebaixado(s) para Free.")


_last_weekly_report = None


def _send_weekly_reports():
    """
    Envia relatório semanal via Telegram para cada cliente com Telegram configurado.
    Dispara toda segunda-feira entre 8h e 9h UTC.
    """
    global _last_weekly_report
    now = datetime.now(timezone.utc)
    now_brt = now.astimezone(_BRT)

    # Só executa segunda-feira (weekday=0), entre 8h e 9h BRT
    if now_brt.weekday() != 0 or now_brt.hour != 8:
        return

    # Evita enviar mais de uma vez por dia
    today_key = now_brt.strftime("%Y-%m-%d")
    if _last_weekly_report == today_key:
        return
    _last_weekly_report = today_key

    week_ago = now - timedelta(days=7)
    clients = Client.query.filter(
        Client.telegram_bot_token.isnot(None),
        Client.telegram_chat_id.isnot(None),
    ).all()

    from modules.telegram_notify import send_telegram

    for client in clients:
        if not client.telegram_bot_token or not client.telegram_chat_id:
            continue
        try:
            total = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= week_ago,
            ).count()
            failed = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "failed",
                PostQueue.created_at >= week_ago,
            ).count()
            pending = PostQueue.query.filter(
                PostQueue.client_id == client.id,
                PostQueue.status == "pending",
            ).count()
            accounts = InstagramAccount.query.filter_by(
                client_id=client.id, status="active"
            ).count()

            plano = "Pro ✨" if client.is_pro() else "Free"
            msg = (
                f"📊 <b>Relatório Semanal — PostSocial</b>\n\n"
                f"📅 Semana: {week_ago.strftime('%d/%m')} a {now.strftime('%d/%m/%Y')}\n\n"
                f"✅ Posts publicados: <b>{total}</b>\n"
                f"❌ Falhas: <b>{failed}</b>\n"
                f"⏳ Na fila: <b>{pending}</b>\n"
                f"📸 Contas ativas: <b>{accounts}</b>\n"
                f"💎 Plano: <b>{plano}</b>\n\n"
                f"<a href='https://captei.shop/dashboard'>Acessar painel →</a>"
            )
            send_telegram(client.telegram_bot_token, client.telegram_chat_id, msg)
            logger.info(f"Relatório semanal enviado para cliente #{client.id}")
        except Exception as e:
            logger.error(f"Erro ao enviar relatório para cliente #{client.id}: {e}")


def process_queue():
    with app.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, igual ao scheduled_at no banco

        # Tarefas de manutenção
        _reset_stuck_processing()
        _cleanup_old_files()
        _check_plan_expirations()
        _send_weekly_reports()

        # Buscar posts prontos (pending + não agendados OU agendamento já passou)
        pending = (
            PostQueue.query.filter_by(status="pending")
            .filter(
                db.or_(
                    PostQueue.scheduled_at.is_(None),
                    PostQueue.scheduled_at <= now,
                )
            )
            .order_by(PostQueue.created_at)
            .all()
        )

        if not pending:
            logger.info("Fila vazia.")
            return

        logger.info(f"{len(pending)} post(s) na fila")

        # Agrupar por conta
        account_posts: dict[int, list[PostQueue]] = {}
        for post in pending:
            acc_id = post.account_id
            if not acc_id:
                # Fallback: pegar primeira conta do cliente
                acc = InstagramAccount.query.filter_by(
                    client_id=post.client_id, status="active"
                ).first()
                if acc:
                    acc_id = acc.id
                    post.account_id = acc.id

            if acc_id:
                account_posts.setdefault(acc_id, []).append(post)
            else:
                post.status = "failed"
                post.error_message = "Nenhuma conta Instagram ativa"
                db.session.commit()

        account_ids = list(account_posts.keys())
        random.shuffle(account_ids)

        for acc_id in account_ids:
            posts = account_posts[acc_id]
            account = db.session.get(InstagramAccount, acc_id)

            if not account or account.status not in ("active", "login_error", "challenge_required"):
                logger.warning(f"Conta #{acc_id} não ativa, pulando")
                continue

            cl = get_ig_client(account)
            if not cl:
                # Se a conta está com login_error permanente, falha os posts
                # que já passaram do horário (não adianta manter em pending)
                if account.status == "login_error":
                    for post in posts:
                        sched = post.scheduled_at or post.created_at
                        if sched and (now - sched).total_seconds() > 7200:  # > 2h
                            post.status = "failed"
                            post.error_message = account.status_message or "Conta Instagram com erro de login."
                            db.session.commit()
                            logger.warning(f"Post #{post.id} marcado como falha — conta @{account.ig_username} inativa há mais de 2h.")
                continue

            # Limite diário anti-bloqueio — máx 2 posts/dia por plataforma
            MAX_PER_DAY = 2
            today_start = datetime.now(_BRT).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
            posted_today = PostQueue.query.filter(
                PostQueue.account_id == acc_id,
                PostQueue.post_type != "story",
                PostQueue.status == "posted",
                PostQueue.post_to_instagram == True,
                PostQueue.posted_at >= today_start,
            ).count()

            remaining = MAX_PER_DAY - posted_today
            if remaining <= 0:
                logger.info(
                    f"[@{account.ig_username}] Limite diário atingido ({MAX_PER_DAY} posts/dia). "
                    f"Adiando para proteger a conta contra shadowban."
                )
                continue

            for i, post in enumerate(posts):
                if i >= remaining:
                    logger.info(f"[@{account.ig_username}] Limite diário ({MAX_PER_DAY}) — posts restantes adiados")
                    break

                post.status = "processing"
                db.session.commit()

                process_post(post, cl, account)

                if i < min(len(posts), remaining) - 1:
                    delay = random.randint(90, 300)  # 1.5 a 5 min entre posts
                    logger.info(f"Aguardando {delay}s (anti-bloqueio)...")
                    time.sleep(delay)

            try:
                session_file = SESSION_DIR / f"account_{acc_id}.json"
                cl.dump_settings(session_file)
            except Exception:
                pass

            if acc_id != account_ids[-1]:
                delay = random.randint(120, 300)
                logger.info(f"Aguardando {delay}s entre contas...")
                time.sleep(delay)

        logger.info("Fila processada.")


_HEARTBEAT_FILE = BASE_DIR / "logs" / "worker_heartbeat.txt"


def _write_heartbeat():
    try:
        _HEARTBEAT_FILE.parent.mkdir(exist_ok=True)
        _HEARTBEAT_FILE.write_text(datetime.now(_BRT).strftime("%Y-%m-%d %H:%M:%S BRT"))
    except Exception:
        pass


def run_daemon(interval: int = 300):
    """Roda em loop contínuo."""
    logger.info(f"Modo daemon — intervalo: {interval}s")
    while True:
        try:
            process_queue()
        except Exception as e:
            logger.error(f"Erro no ciclo: {e}")
        _write_heartbeat()
        logger.info(f"Próximo ciclo em {interval}s...")
        time.sleep(interval)


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("PostSocial Worker")
    logger.info("=" * 60)

    if "--daemon" in sys.argv:
        interval = 300  # 5 minutos
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])
        run_daemon(interval)
    else:
        process_queue()
