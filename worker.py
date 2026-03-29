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
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from instagrapi import Client as IGClient
from instagrapi.exceptions import (
    LoginRequired, ChallengeRequired, TwoFactorRequired,
    BadPassword, PleaseWaitFewMinutes,
)

from app import create_app
from app.models import db, PostQueue, InstagramAccount, Client
from modules.caption_generator import CaptionGenerator
from modules.logger import setup_global_logger

BASE_DIR = Path(__file__).parent
SESSION_DIR = BASE_DIR / "sessions"
SESSION_DIR.mkdir(exist_ok=True)

app = create_app()
logger = setup_global_logger(str(BASE_DIR))


def get_ig_client(account: InstagramAccount) -> IGClient | None:
    cl = IGClient()
    cl.delay_range = [2, 5]

    session_file = SESSION_DIR / f"account_{account.id}.json"
    username = account.ig_username
    password = account.get_ig_password()

    if session_file.exists():
        try:
            cl.load_settings(session_file)
            cl.login(username, password)
            cl.get_timeline_feed()
            logger.info(f"[@{username}] Sessão restaurada")
            return cl
        except Exception as e:
            logger.warning(f"[@{username}] Sessão expirada: {e}")
            session_file.unlink(missing_ok=True)

    try:
        logger.info(f"[@{username}] Login fresh...")
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
        account.status_message = "Senha incorreta."
        db.session.commit()
        return None

    except ChallengeRequired:
        logger.error(f"[@{username}] Challenge required")
        account.status = "challenge_required"
        account.status_message = "Verificação necessária. Faça login pelo app do celular e tente novamente."
        db.session.commit()
        return None

    except TwoFactorRequired:
        logger.error(f"[@{username}] 2FA ativo")
        account.status = "login_error"
        account.status_message = "2FA ativo. Desative ou use senha de app."
        db.session.commit()
        return None

    except PleaseWaitFewMinutes:
        logger.error(f"[@{username}] Rate limit")
        account.status_message = "Rate limit. Tentaremos novamente em breve."
        db.session.commit()
        return None

    except Exception as e:
        logger.error(f"[@{username}] Erro: {e}")
        account.status = "login_error"
        account.status_message = str(e)[:200]
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

            db.session.commit()
            logger.info(f"Post #{post.id} — POSTADO! ID: {media_id}")
            return True

        post.status = "failed"
        post.error_message = "Upload retornou vazio"
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
        post.status = "failed"
        post.error_message = f"{type(e).__name__}: {str(e)[:200]}"

        client = db.session.get(Client, post.client_id)
        if client:
            send_email_notification(client, post, success=False)

        db.session.commit()
        logger.error(f"Post #{post.id} — Erro: {e}")
        return False


def process_queue():
    with app.app_context():
        now = datetime.now(timezone.utc)

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

            if not account or account.status != "active":
                logger.warning(f"Conta #{acc_id} não ativa, pulando")
                continue

            cl = get_ig_client(account)
            if not cl:
                continue

            # Limite diário anti-bloqueio
            MAX_PER_DAY = 5
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            posted_today = PostQueue.query.filter(
                PostQueue.account_id == acc_id,
                PostQueue.status == "posted",
                PostQueue.posted_at >= today_start,
            ).count()

            remaining = MAX_PER_DAY - posted_today
            if remaining <= 0:
                logger.info(f"[@{account.ig_username}] Limite diário atingido ({MAX_PER_DAY}). Adiando.")
                continue

            for i, post in enumerate(posts):
                if i >= remaining:
                    logger.info(f"[@{account.ig_username}] Limite diário ({MAX_PER_DAY}) - posts restantes adiados")
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


def run_daemon(interval: int = 300):
    """Roda em loop contínuo."""
    logger.info(f"Modo daemon — intervalo: {interval}s")
    while True:
        try:
            process_queue()
        except Exception as e:
            logger.error(f"Erro no ciclo: {e}")
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
