"""Logging estruturado, transversal a todas as camadas."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


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
