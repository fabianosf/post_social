"""
Módulo de logging estruturado para o PostSocial.
Registra todas as operações, erros de login e bloqueios de API.
"""

import logging
import os
from datetime import datetime
from pathlib import Path


def setup_logger(client_id: str, base_dir: str = ".") -> logging.Logger:
    """Cria um logger dedicado por cliente com output em arquivo e console."""

    log_dir = Path(base_dir) / "clients" / client_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"{datetime.now().strftime('%Y-%m')}.log"

    logger = logging.getLogger(f"postsocial.{client_id}")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Arquivo
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


def setup_global_logger(base_dir: str = ".") -> logging.Logger:
    """Logger global para operações do sistema."""

    log_dir = Path(base_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"system_{datetime.now().strftime('%Y-%m')}.log"

    logger = logging.getLogger("postsocial.system")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [SYSTEM] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger
