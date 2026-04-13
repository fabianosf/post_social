"""
Notificações via Telegram Bot para o PostSocial.
"""
import urllib.request
import urllib.parse
import json


def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    """Envia mensagem via Telegram Bot API. Retorna True se enviou."""
    if not bot_token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception:
        return False


def _diagnose_error(error: str) -> tuple[str, str]:
    """
    Analisa a mensagem de erro e retorna (causa, ação recomendada).
    """
    err = error.lower()

    if any(k in err for k in ["challenge_required", "challenge required", "verification"]):
        return (
            "Instagram pediu verificação de segurança",
            "Acesse o painel admin → Resolver verificação e complete o processo.",
        )
    if any(k in err for k in ["login_required", "login required", "not logged in", "session"]):
        return (
            "Sessão do Instagram expirada",
            "Reconecte a conta no painel: Contas → desconectar e reconectar.",
        )
    if any(k in err for k in ["rate limit", "ratelimit", "too many", "spam", "feedback_required"]):
        return (
            "Limite de posts atingido no Instagram",
            "Aguarde algumas horas antes de postar novamente. O post será reagendado automaticamente.",
        )
    if any(k in err for k in ["media upload", "upload", "file", "video", "image"]):
        return (
            "Erro no upload da mídia",
            "Verifique se o arquivo não está corrompido. Tente repostar com um arquivo diferente.",
        )
    if any(k in err for k in ["timeout", "connection", "network", "urllib", "ssl"]):
        return (
            "Erro de rede/conexão",
            "Falha temporária de rede. O sistema tentará novamente automaticamente.",
        )
    if any(k in err for k in ["caption", "texto", "hashtag"]):
        return (
            "Erro na legenda ou hashtags",
            "Verifique se a legenda não contém caracteres inválidos.",
        )
    if "tiktok" in err:
        return (
            "Erro na publicação do TikTok",
            "Verifique se o token do TikTok está válido. Reconecte o TikTok se necessário.",
        )

    return ("Erro inesperado durante a publicação", "Verifique o painel e tente repostar manualmente.")


def notify_post_success(client, post, account):
    """Notifica quando um post é publicado com sucesso."""
    if not client.telegram_bot_token or not client.telegram_chat_id:
        return

    plataformas = []
    if getattr(post, "post_to_instagram", True):
        plataformas.append("Instagram")
    if getattr(post, "post_to_facebook", False):
        plataformas.append("Facebook")
    if getattr(post, "post_to_tiktok", False):
        plataformas.append("TikTok")
    plats = " + ".join(plataformas) if plataformas else "—"

    caption_preview = ""
    if post.caption:
        caption_preview = f"\n📝 <i>{post.caption[:80]}{'...' if len(post.caption) > 80 else ''}</i>"

    msg = (
        f"✅ <b>Post publicado com sucesso!</b>\n\n"
        f"👤 Conta: <b>@{account.ig_username}</b>\n"
        f"🌐 Plataformas: {plats}\n"
        f"🗂 Arquivo: {post.image_filename[:40]}"
        f"{caption_preview}"
    )
    send_telegram(client.telegram_bot_token, client.telegram_chat_id, msg)


def notify_post_failed(client, post, account, error: str):
    """Notifica quando um post falha, com diagnóstico e ação recomendada."""
    if not client.telegram_bot_token or not client.telegram_chat_id:
        return

    causa, acao = _diagnose_error(error)
    retry = getattr(post, "retry_count", 0)
    retry_info = ""
    if retry < 3:
        retry_info = f"\n🔁 <i>O sistema tentará novamente automaticamente ({retry}/3).</i>"
    else:
        retry_info = "\n🛑 <i>Número máximo de tentativas atingido. Verifique manualmente.</i>"

    msg = (
        f"❌ <b>Falha ao publicar post!</b>\n\n"
        f"👤 Conta: <b>@{account.ig_username}</b>\n"
        f"🗂 Arquivo: {post.image_filename[:40]}\n\n"
        f"🔍 <b>Causa:</b> {causa}\n"
        f"💡 <b>O que fazer:</b> {acao}"
        f"{retry_info}\n\n"
        f"<code>{error[:150]}</code>"
    )
    send_telegram(client.telegram_bot_token, client.telegram_chat_id, msg)


def notify_session_expiring(client, account, days_since_login: int):
    """Avisa que a sessão do Instagram está prestes a expirar."""
    if not client.telegram_bot_token or not client.telegram_chat_id:
        return
    urgency = "🔴" if days_since_login > 85 else "🟡"
    msg = (
        f"{urgency} <b>Sessão Instagram prestes a expirar!</b>\n\n"
        f"👤 Conta: <b>@{account.ig_username}</b>\n"
        f"📅 Último login: há {days_since_login} dias\n\n"
        f"💡 Reconecte a conta no painel para evitar falhas de publicação."
    )
    send_telegram(client.telegram_bot_token, client.telegram_chat_id, msg)
