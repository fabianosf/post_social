#!/usr/bin/env python3
"""
PostSocial - Micro-SaaS de Automação de Postagens Instagram + Facebook
Orquestrador principal: carrega clientes, processa postagens sequencialmente
com delay aleatório entre clientes para evitar detecção de bot.
"""

import json
import random
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from modules.caption_generator import CaptionGenerator
from modules.file_manager import FileManager
from modules.instagram_poster import InstagramPoster
from modules.facebook_poster import FacebookPoster
from modules.logger import setup_logger, setup_global_logger

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config" / "clients.json"

# Delay aleatório entre clientes (segundos)
MIN_DELAY_BETWEEN_CLIENTS = 60
MAX_DELAY_BETWEEN_CLIENTS = 180


def load_clients() -> list[dict]:
    """Carrega configuração de todos os clientes."""
    if not CONFIG_FILE.exists():
        print(f"ERRO: Arquivo de configuração não encontrado: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("clients", [])


def generate_caption(client_config: dict, image_name: str, logger) -> str:
    """Gera legenda via IA ou fallback."""
    caption_settings = client_config.get("caption_settings", {})

    if caption_settings.get("use_ai_caption", False):
        ai_provider = caption_settings.get("ai_provider", "groq")
        caption_gen = CaptionGenerator(logger, provider=ai_provider)
        return caption_gen.generate(
            image_name=image_name,
            tone=caption_settings.get("tone", "profissional"),
            language=caption_settings.get("language", "pt-br"),
            default_hashtags=caption_settings.get("default_hashtags", []),
        )

    hashtags = " ".join(caption_settings.get("default_hashtags", []))
    description = image_name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
    return f"✨ {description}\n\n{hashtags}"


def post_to_instagram(client_config: dict, image_path: str, caption: str, logger) -> bool:
    """Posta no Instagram. Retorna True se sucesso."""
    ig_config = client_config.get("instagram", {})
    if not ig_config.get("enabled", True):
        logger.info("[Instagram] Desabilitado para este cliente. Pulando.")
        return False

    username = ig_config.get("username")
    password = ig_config.get("password")

    if not username or not password:
        logger.warning("[Instagram] Credenciais não configuradas. Pulando.")
        return False

    poster = InstagramPoster(
        username=username,
        password=password,
        client_id=client_config["id"],
        logger=logger,
    )

    if not poster.login():
        logger.error("[Instagram] Falha no login.")
        return False

    media_id = poster.post_photo(image_path, caption)
    poster.logout()

    if media_id:
        logger.info(f"[Instagram] Sucesso! Media ID: {media_id}")
        return True

    logger.error("[Instagram] Falha na postagem.")
    return False


def post_to_facebook(client_config: dict, image_path: str, caption: str, logger) -> bool:
    """Posta no Facebook. Retorna True se sucesso."""
    fb_config = client_config.get("facebook", {})
    if not fb_config.get("enabled", True):
        logger.info("[Facebook] Desabilitado para este cliente. Pulando.")
        return False

    page_id = fb_config.get("page_id")
    access_token = fb_config.get("access_token")

    if not page_id or not access_token:
        logger.warning("[Facebook] Credenciais não configuradas. Pulando.")
        return False

    poster = FacebookPoster(
        page_id=page_id,
        access_token=access_token,
        client_id=client_config["id"],
        logger=logger,
    )

    if not poster.validate_token():
        logger.error("[Facebook] Token inválido.")
        return False

    post_id, _permalink, _err = poster.post_photo(image_path, caption)

    if post_id:
        logger.info(f"[Facebook] Sucesso! Post ID: {post_id}")
        return True

    logger.error("[Facebook] Falha na postagem.")
    return False


def process_client(client_config: dict, system_logger) -> bool:
    """
    Processa um cliente: busca imagem, gera legenda, posta no Instagram e Facebook.
    Retorna True se postou com sucesso em pelo menos uma rede.
    """
    client_id = client_config["id"]
    logger = setup_logger(client_id, str(BASE_DIR))

    logger.info(f"=== Processando cliente: {client_config['name']} ===")

    # Verificar se está habilitado
    schedule = client_config.get("posting_schedule", {})
    if not schedule.get("enabled", True):
        logger.info("Cliente desabilitado. Pulando.")
        return False

    # Gerenciador de arquivos
    folders = client_config["folders"]
    file_mgr = FileManager(
        entrada_dir=str(BASE_DIR / folders["entrada"]),
        postados_dir=str(BASE_DIR / folders["postados"]),
        logger=logger,
    )

    # Buscar próxima imagem
    image = file_mgr.get_next_image()
    if not image:
        return False

    # Gerar legenda (mesma para ambas as redes)
    caption = generate_caption(client_config, image.name, logger)
    logger.info(f"Legenda: {caption[:80]}...")

    # Postar nas redes configuradas
    ig_ok = post_to_instagram(client_config, str(image), caption, logger)
    fb_ok = post_to_facebook(client_config, str(image), caption, logger)

    # Mover para postados se pelo menos uma rede teve sucesso
    if ig_ok or fb_ok:
        file_mgr.move_to_posted(image)
        redes = []
        if ig_ok:
            redes.append("Instagram")
        if fb_ok:
            redes.append("Facebook")
        logger.info(f"Postado com sucesso em: {', '.join(redes)}")
        return True

    logger.error("Falha em todas as redes.")
    return False


def main():
    system_logger = setup_global_logger(str(BASE_DIR))
    system_logger.info("=" * 60)
    system_logger.info("PostSocial - Iniciando ciclo de postagens")
    system_logger.info("=" * 60)

    clients = load_clients()
    if not clients:
        system_logger.warning("Nenhum cliente configurado.")
        return

    system_logger.info(f"Clientes carregados: {len(clients)}")

    # Embaralhar ordem dos clientes (anti-pattern detection)
    random.shuffle(clients)

    results = {"success": 0, "failed": 0, "skipped": 0}

    for i, client in enumerate(clients):
        try:
            success = process_client(client, system_logger)
            if success:
                results["success"] += 1
            else:
                results["skipped"] += 1
        except Exception as e:
            system_logger.error(
                f"Erro crítico no cliente {client.get('id', '?')}: "
                f"{type(e).__name__}: {e}"
            )
            results["failed"] += 1

        # Delay entre clientes (exceto o último)
        if i < len(clients) - 1:
            delay = random.randint(MIN_DELAY_BETWEEN_CLIENTS, MAX_DELAY_BETWEEN_CLIENTS)
            system_logger.info(f"Aguardando {delay}s antes do próximo cliente...")
            time.sleep(delay)

    system_logger.info(
        f"Ciclo finalizado. "
        f"Sucesso: {results['success']} | "
        f"Falhas: {results['failed']} | "
        f"Ignorados: {results['skipped']}"
    )


if __name__ == "__main__":
    main()
