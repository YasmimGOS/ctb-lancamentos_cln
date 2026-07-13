"""Logging estruturado, transversal a todas as camadas."""
from __future__ import annotations

import logging
import os
import platform
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_IS_WINDOWS = platform.system() == "Windows"


def sanitize_emoji(msg: str) -> str:
    """Remove emojis da mensagem se executando em Linux.

    No Windows, mantém os emojis.
    No Linux, remove para evitar problemas de renderização no terminal.

    Args:
        msg: Mensagem que pode conter emojis

    Returns:
        Mensagem sanitizada (sem emojis no Linux, com emojis no Windows)
    """
    if _IS_WINDOWS:
        return msg

    # Padrão regex para remover emojis comuns
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F9FF"  # Emojis diversos
        "\U0001F600-\U0001F64F"  # Emoticons
        "\U0001F680-\U0001F6FF"  # Símbolos de transporte
        "\U00002600-\U000027BF"  # Símbolos diversos
        "\U0001F1E0-\U0001F1FF"  # Bandeiras
        "\U0001F900-\U0001F9FF"  # Símbolos suplementares
        "\U00002300-\U000023FF"  # Símbolos técnicos diversos
        "\U0000FE00-\U0000FE0F"  # Seletores de variação
        "\U0001F200-\U0001F2FF"  # Ideogramas circulados
        "]+",
        flags=re.UNICODE,
    )

    return emoji_pattern.sub("", msg).strip()


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()

    # Criar pasta logs se nao existir
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Nome do arquivo de log com timestamp completo (data + hora)
    log_file = logs_dir / f"ctb-lancamentos_cln_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Formato detalhado para arquivo
    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-30s | %(funcName)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Formato simples para console
    console_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler para arquivo (rotativo: max 10MB, 5 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # Arquivo registra tudo
    file_handler.setFormatter(file_formatter)

    # Handler para console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)

    # Configurar logger raiz
    root = logging.getLogger("lancamento_cln")
    root.setLevel(logging.DEBUG)  # Logger aceita tudo, handlers filtram
    root.handlers[:] = [console_handler, file_handler]
    root.propagate = False

    _CONFIGURED = True

    # Log inicial
    root.info("=" * 80)
    root.info(f"Inicio do disparo LancamentoCLN - {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    root.info("=" * 80)


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(f"lancamento_cln.{name}")
