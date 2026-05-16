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

_PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://postay.com.br").rstrip("/")


def _ig_connection_type(account: InstagramAccount) -> str:
    t = getattr(account, "ig_connection_type", None) or "password"
    return str(t).strip() or "password"


app = create_app()
logger = setup_global_logger(str(BASE_DIR))


_LOGIN_ERROR_COOLDOWN_MINUTES = 30    # Erro genérico: retry após 30 min
_NOT_FOUND_COOLDOWN_MINUTES   = 1440  # Usuário não encontrado: retry após 24h

MAX_PUBLISH_RETRIES = 3
RETRY_DELAYS_MIN = [15, 30, 60]


def _is_transient_error(msg: str) -> bool:
    m = (msg or "").lower()
    if not m:
        return False
    if any(
        x in m
        for x in (
            "expired",
            "invalid oauth",
            "session has been invalidated",
            "190",
            "auth_removed",
            "spam_risk",
            "user_banned",
            "publish_cancelled",
            "access_token_invalid",
            "token_not_authorized",
            "reconecte",
            "não encontrado",
            "arquivo(s) não encontrado",
        )
    ):
        return False
    return any(
        x in m
        for x in (
            "timeout",
            "temporarily",
            "rate limit",
            "try again",
            "internal",
            "503",
            "502",
            "429",
            "500",
            "service unavailable",
            "network",
            "connection",
            "busy",
            "throttle",
            "please wait",
            "aguardando",
            "processing",
            "tentativa",
        )
    )


def _schedule_publish_retry(post: PostQueue, err_s: str, label: str = "") -> bool:
    """Agenda retry em pending. True=agendado, False=falha final."""
    err_s = (err_s or "Erro temporário na API")[:500]
    post.retry_count = (post.retry_count or 0) + 1
    tag = f"({label}) " if label else ""
    if post.retry_count <= MAX_PUBLISH_RETRIES and _is_transient_error(err_s):
        delay = RETRY_DELAYS_MIN[min(post.retry_count - 1, len(RETRY_DELAYS_MIN) - 1)]
        post.status = "pending"
        post.scheduled_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            minutes=delay
        )
        post.error_message = (
            f"Tentativa {post.retry_count}/{MAX_PUBLISH_RETRIES} {tag}{err_s}"
        )[:500]
        logger.warning(
            f"Post #{post.id} — retry {post.retry_count}/{MAX_PUBLISH_RETRIES} em {delay}min"
        )
        return True
    post.status = "failed"
    post.error_message = (
        f"Falhou após {post.retry_count} tentativa(s). {tag}{err_s}"
    )[:500]
    return False


def get_ig_client(account: InstagramAccount) -> IGClient | None:
    if _ig_connection_type(account) == "graph_oauth":
        return None

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


def _resume_partial_publish(post: PostQueue, account: InstagramAccount) -> bool:
    """Continua FB/TikTok sem republicar no Instagram."""
    client = db.session.get(Client, post.client_id)
    paths = post.image_path.split("|")
    caption = post.caption or generate_caption(post)
    post.caption = caption
    token = account.get_ig_password()

    if (
        post.post_to_facebook
        and account.share_to_facebook
        and account.ig_graph_page_id
        and not post.fb_post_id
    ):
        try:
            from modules.facebook_poster import FacebookPoster

            fb = FacebookPoster(
                str(account.ig_graph_page_id), token, str(account.client_id), logger
            )
            fb_id, fb_link, fb_err = fb.post_photo(paths[0], caption)
            if fb_id:
                post.fb_post_id = fb_id
                post.fb_permalink = fb_link
                post.fb_error_message = None if fb_link else f"Sem permalink (post_id {fb_id})"
            elif fb_err:
                post.fb_error_message = fb_err
        except Exception as e:
            post.fb_error_message = f"{type(e).__name__}: {e}"

    if post.post_to_tiktok and not post.tiktok_publish_id:
        if not _try_post_tiktok(post, client):
            err = post.tiktok_link_error or "Falha TikTok"
            if _schedule_publish_retry(post, err, "TikTok"):
                db.session.commit()
                return False

    was_new = post.status != "posted"
    post.status = "posted"
    if not post.posted_at:
        post.posted_at = datetime.now(timezone.utc)
    post.error_message = None
    if client and was_new:
        client.increment_post_count()
        send_email_notification(client, post, success=True)
        notify_post_success(client, post, account)
    db.session.commit()
    logger.info(f"Post #{post.id} — retomada parcial concluída (sem duplicar IG)")
    return True


def process_post_graph_oauth(post: PostQueue, account: InstagramAccount) -> bool:
    """Publica foto no feed via Instagram Graph API (conta conectada por OAuth Meta)."""
    from urllib.parse import quote

    from flask import current_app

    from modules import instagram_graph as ig_graph

    if post.instagram_media_id:
        return _resume_partial_publish(post, account)

    paths = post.image_path.split("|")
    if not all(os.path.exists(p) for p in paths):
        post.status = "failed"
        post.error_message = "Arquivo(s) não encontrado(s)"
        db.session.commit()
        return False

    if post.post_type != "photo":
        post.status = "failed"
        post.error_message = (
            "Conta conectada via Meta: por enquanto só fotos no feed. "
            "Para Reels/Carrossel/Stories use o método clássico ou reconecte."
        )
        db.session.commit()
        return False

    ig_uid = (account.ig_graph_user_id or "").strip()
    if not ig_uid:
        post.status = "failed"
        post.error_message = "Conta Meta sem ID do Instagram — reconecte pelo painel."
        db.session.commit()
        return False

    caption = generate_caption(post)
    post.caption = caption
    logger.info(f"Post #{post.id} [graph photo] — {caption[:60]}...")

    uf = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    first = Path(paths[0]).resolve()
    try:
        rel = str(first.relative_to(uf))
    except ValueError:
        post.status = "failed"
        post.error_message = "Mídia precisa estar em /uploads para URL pública (Meta)."
        db.session.commit()
        return False

    image_url = f"{_PUBLIC_BASE}/uploads/{quote(rel, safe='/')}"
    token = account.get_ig_password()

    mid, err, ig_permalink, ig_media_url, ig_link_err = ig_graph.publish_single_image(
        ig_uid, token, image_url, caption
    )
    if mid:
        post.instagram_media_id = mid
        post.ig_permalink = ig_permalink
        post.ig_media_url = ig_media_url
        post.ig_link_error = ig_link_err if not ig_permalink else None
        post.error_message = None
        post.fb_error_message = None

        client = db.session.get(Client, post.client_id)

        if post.post_to_facebook and account.share_to_facebook and account.ig_graph_page_id:
            try:
                from modules.facebook_poster import FacebookPoster

                fb = FacebookPoster(
                    str(account.ig_graph_page_id),
                    token,
                    str(account.client_id),
                    logger,
                )
                fb_id, fb_link, fb_err = fb.post_photo(paths[0], caption)
                if fb_id:
                    post.fb_post_id = fb_id
                    post.fb_permalink = fb_link
                    if not fb_link:
                        post.fb_error_message = (
                            "Facebook: publicado (post_id %s), mas a API não retornou permalink."
                            % fb_id
                        )
                elif fb_err:
                    post.fb_error_message = fb_err
            except Exception as fb_e:
                post.fb_error_message = f"{type(fb_e).__name__}: {fb_e}"
                logger.warning(f"Post #{post.id} — Facebook espelho falhou: {fb_e}")

        if getattr(post, "post_to_tiktok", False) and not post.tiktok_publish_id:
            if not _try_post_tiktok(post, client):
                err = post.tiktok_link_error or "Falha TikTok"
                if _schedule_publish_retry(post, err, "TikTok"):
                    db.session.commit()
                    return False

        post.status = "posted"
        post.posted_at = datetime.now(timezone.utc)
        db.session.commit()
        logger.info(f"Post #{post.id} — POSTADO Instagram (Meta Graph)! ID: {mid}")

        if client:
            client.increment_post_count()
            send_email_notification(client, post, success=True)
            notify_post_success(client, post, account)

        return True

    err_s = (err or "Falha desconhecida na API Meta")[:500]
    el = err_s.lower()
    if "expired" in el or "190" in err_s or "invalid oauth" in el or "session has been invalidated" in el:
        account.status = "login_error"
        account.status_message = "Acesso Meta expirado. Use «Conectar com Meta» no painel para reconectar."
        account.last_login_at = datetime.now(timezone.utc)
        post.status = "failed"
        post.error_message = err_s
        client = db.session.get(Client, post.client_id)
        if client:
            send_email_notification(client, post, success=False)
            notify_post_failed(client, post, account, err_s)
        db.session.commit()
        return False

    client = db.session.get(Client, post.client_id)
    if _schedule_publish_retry(post, err_s, "Meta"):
        db.session.commit()
    else:
        if client:
            send_email_notification(client, post, success=False)
            notify_post_failed(client, post, account, post.error_message or err_s)
        db.session.commit()
        logger.error(f"Post #{post.id} — falha final Meta: {err_s}")

    return False


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
    if post.instagram_media_id:
        client = db.session.get(Client, post.client_id)
        if getattr(post, "post_to_tiktok", False) and not post.tiktok_publish_id:
            if not _try_post_tiktok(post, client):
                err = post.tiktok_link_error or "Falha TikTok"
                if _schedule_publish_retry(post, err, "TikTok"):
                    db.session.commit()
                    return False
        post.status = "posted"
        if not post.posted_at:
            post.posted_at = datetime.now(timezone.utc)
        post.error_message = None
        db.session.commit()
        return True

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
            post.ig_permalink = None
            post.ig_media_url = None
            try:
                info = cl.media_info(int(media_id))
                if info and getattr(info, "code", None):
                    post.ig_permalink = f"https://www.instagram.com/p/{info.code}/"
                thumb = getattr(info, "thumbnail_url", None)
                if thumb:
                    post.ig_media_url = str(thumb)
            except Exception:
                pass
            post.error_message = None
            client = db.session.get(Client, post.client_id)

            if getattr(post, "post_to_tiktok", False) and not post.tiktok_publish_id:
                if not _try_post_tiktok(post, client):
                    err = post.tiktok_link_error or "Falha TikTok"
                    if _schedule_publish_retry(post, err, "TikTok"):
                        db.session.commit()
                        return False

            post.status = "posted"
            post.posted_at = datetime.now(timezone.utc)
            db.session.commit()
            logger.info(f"Post #{post.id} — POSTADO Instagram! ID: {media_id}")

            if client:
                client.increment_post_count()
                send_email_notification(client, post, success=True)
                notify_post_success(client, post, account)

            return True

        post.status = "failed"
        post.error_message = "Upload retornou vazio"
        client = db.session.get(Client, post.client_id)
        if client:
            notify_post_failed(client, post, account, "Upload retornou vazio")
        db.session.commit()
        return False

    except PleaseWaitFewMinutes as e:
        if _schedule_publish_retry(post, str(e) or "Rate limit Instagram", "IG"):
            db.session.commit()
        else:
            post.status = "failed"
            post.error_message = "Rate limit — limite de tentativas atingido"
            db.session.commit()
        return False

    except LoginRequired:
        post.status = "failed"
        post.error_message = "Sessão expirada — reconecte a conta no painel"
        session_file = SESSION_DIR / f"account_{account.id}.json"
        session_file.unlink(missing_ok=True)
        db.session.commit()
        return False

    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)[:200]}"
        client = db.session.get(Client, post.client_id)
        if _schedule_publish_retry(post, err_msg, "IG"):
            db.session.commit()
            logger.warning(f"Post #{post.id} — retry agendado: {e}")
        else:
            if client:
                send_email_notification(client, post, success=False)
                notify_post_failed(
                    client, post, account, post.error_message or err_msg
                )
            db.session.commit()
            logger.error(f"Post #{post.id} — FALHA FINAL: {e}")
        return False


def _try_post_tiktok(post: PostQueue, client: Client | None) -> bool:
    """Tenta postar no TikTok. Retorna True se publicou (publish_id)."""
    try:
        from app.routes_tiktok import fetch_tiktok_post_url, post_to_tiktok

        tiktok_acc = TikTokAccount.query.filter_by(client_id=post.client_id).first()
        if not tiktok_acc:
            post.tiktok_link_error = "Nenhuma conta TikTok conectada"
            logger.warning(f"Post #{post.id} — TikTok marcado mas nenhuma conta conectada.")
            return False
        publish_id = post_to_tiktok(tiktok_acc, post)
        if not publish_id:
            post.tiktok_link_error = "TikTok não retornou publish_id"
            return False
        post.tiktok_publish_id = publish_id
        url, video_id, link_err = fetch_tiktok_post_url(tiktok_acc, publish_id)
        post.tiktok_permalink = url
        post.tiktok_video_id = video_id
        post.tiktok_link_error = link_err if not url else None
        logger.info(
            f"Post #{post.id} — TikTok publish_id={publish_id} video_id={video_id} url={url}"
        )
        return True
    except Exception as e:
        post.tiktok_link_error = f"{type(e).__name__}: {str(e)[:300]}"
        logger.error(f"Post #{post.id} — Erro TikTok: {e}")
        return False


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
        Client.plan.in_(["pro", "agency"]),
        Client.is_admin == False,
        Client.plan_expires_at.isnot(None),
        Client.plan_expires_at <= now_utc,
    ).all()

    for client in expired:
        logger.warning(f"Cliente #{client.id} ({client.email}) — plano {client.plan} expirado.")
        client.plan = "free"
        client.mp_subscription_id = None

        if client.telegram_bot_token and client.telegram_chat_id:
            from modules.telegram_notify import send_telegram
            send_telegram(
                client.telegram_bot_token,
                client.telegram_chat_id,
                "⚠️ <b>Assinatura expirada</b>\n\n"
                "Seu plano venceu e foi rebaixado para Free.\n"
                "Renove em: <a href='https://postay.com.br/pagamento'>postay.com.br/pagamento</a>"
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

            plano = "Agency ✨" if client.plan == "agency" else ("Pro ✨" if client.has_pro_features() else "Free")
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

            if _ig_connection_type(account) == "graph_oauth":
                if account.status == "login_error":
                    for post in posts:
                        sched = post.scheduled_at or post.created_at
                        if sched and (now - sched).total_seconds() > 7200:
                            post.status = "failed"
                            post.error_message = account.status_message or "Reconecte o Instagram com Meta."
                            db.session.commit()
                    continue
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
                    logger.info(f"[Graph @{account.ig_username}] limite diário atingido.")
                    continue
                for i, post in enumerate(posts):
                    if i >= remaining:
                        break
                    post.status = "processing"
                    db.session.commit()
                    process_post_graph_oauth(post, account)
                    if i < min(len(posts), remaining) - 1:
                        delay = random.randint(90, 300)
                        logger.info(f"Aguardando {delay}s (anti-bloqueio)...")
                        time.sleep(delay)
                if acc_id != account_ids[-1]:
                    delay = random.randint(120, 300)
                    logger.info(f"Aguardando {delay}s entre contas...")
                    time.sleep(delay)
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

        with app.app_context():
            failed_n = PostQueue.query.filter_by(status="failed").count()
            proc_n = PostQueue.query.filter_by(status="processing").count()
            pend_n = PostQueue.query.filter_by(status="pending").count()
            if failed_n >= 10 or proc_n >= 5:
                logger.warning(
                    "CRITICAL fila: pending=%s processing=%s failed=%s",
                    pend_n, proc_n, failed_n,
                )
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
        _write_heartbeat()
