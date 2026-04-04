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


def notify_post_success(client, post, account):
    """Notifica quando um post é publicado com sucesso."""
    if not client.telegram_bot_token or not client.telegram_chat_id:
        return
    plataformas = []
    if post.post_to_instagram:
        plataformas.append("Instagram")
    if post.post_to_facebook:
        plataformas.append("Facebook")
    plats = " + ".join(plataformas)
    msg = (
        f"✅ <b>Post publicado!</b>\n"
        f"📸 Conta: @{account.ig_username}\n"
        f"🌐 Plataforma: {plats}\n"
        f"📝 {(post.caption or '')[:80]}{'...' if post.caption and len(post.caption) > 80 else ''}"
    )
    send_telegram(client.telegram_bot_token, client.telegram_chat_id, msg)


def notify_post_failed(client, post, account, error: str):
    """Notifica quando um post falha."""
    if not client.telegram_bot_token or not client.telegram_chat_id:
        return
    msg = (
        f"❌ <b>Falha ao publicar post!</b>\n"
        f"📸 Conta: @{account.ig_username}\n"
        f"🗂 Arquivo: {post.image_filename[:40]}\n"
        f"⚠️ Erro: {error[:200]}"
    )
    send_telegram(client.telegram_bot_token, client.telegram_chat_id, msg)
