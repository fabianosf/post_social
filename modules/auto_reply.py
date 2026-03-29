"""
Auto-reply — Responde automaticamente a comentários no Instagram.
Rodar via cron ou junto com o worker.
"""

import os
import time
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv()


DEFAULT_REPLIES = [
    "Obrigado pelo comentário! 😊",
    "Que bom que gostou! ❤️",
    "Muito obrigado! 🙏",
    "Agradecemos o carinho! 💜",
    "Valeu demais! 🔥",
]


def process_auto_replies(logger=None):
    """Verifica posts recentes e responde comentários não respondidos."""
    try:
        from instagrapi import Client as IGClient
    except ImportError:
        if logger:
            logger.error("instagrapi não instalado")
        return

    from app import create_app
    from app.models import db, PostQueue, InstagramAccount

    app = create_app()
    session_dir = Path(__file__).parent.parent / "sessions"

    with app.app_context():
        # Posts das últimas 48h que foram postados
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        recent_posts = (
            PostQueue.query.filter(
                PostQueue.status == "posted",
                PostQueue.posted_at >= cutoff,
                PostQueue.instagram_media_id.isnot(None),
            )
            .all()
        )

        if not recent_posts:
            if logger:
                logger.info("Auto-reply: nenhum post recente para verificar")
            return

        # Agrupar por conta
        account_posts: dict[int, list[PostQueue]] = {}
        for post in recent_posts:
            if post.account_id:
                account_posts.setdefault(post.account_id, []).append(post)

        for acc_id, posts in account_posts.items():
            account = db.session.get(InstagramAccount, acc_id)
            if not account or account.status != "active":
                continue

            cl = IGClient()
            session_file = session_dir / f"account_{acc_id}.json"

            if not session_file.exists():
                continue

            try:
                cl.load_settings(session_file)
                cl.login(account.ig_username, account.get_ig_password())
            except Exception as e:
                if logger:
                    logger.warning(f"Auto-reply: login falhou para @{account.ig_username}: {e}")
                continue

            for post in posts:
                try:
                    media_id = int(post.instagram_media_id)
                    comments = cl.media_comments(media_id, amount=20)

                    for comment in comments:
                        # Pular nossos próprios comentários
                        if comment.user.username == account.ig_username:
                            continue

                        # Verificar se já respondemos (buscar replies)
                        # Simplificação: responder apenas se comentário é recente (<6h)
                        if comment.created_at_utc:
                            age = datetime.now(timezone.utc) - comment.created_at_utc
                            if age > timedelta(hours=6):
                                continue

                        reply = random.choice(DEFAULT_REPLIES)
                        cl.media_comment(media_id, f"@{comment.user.username} {reply}")

                        if logger:
                            logger.info(
                                f"Auto-reply: respondeu @{comment.user.username} no post #{post.id}"
                            )

                        time.sleep(random.randint(10, 30))

                except Exception as e:
                    if logger:
                        logger.warning(f"Auto-reply erro post #{post.id}: {e}")

            # Salvar sessão
            try:
                cl.dump_settings(session_file)
            except Exception:
                pass

            time.sleep(random.randint(30, 60))


if __name__ == "__main__":
    from modules.logger import setup_global_logger

    logger = setup_global_logger(str(Path(__file__).parent.parent))
    process_auto_replies(logger)
