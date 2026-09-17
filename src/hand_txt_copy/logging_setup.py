"""Logging configuration: console + rotating file, for AOI traceability."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LoggingConfig

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(cfg: LoggingConfig) -> None:
    """Configure the root logger with a console handler and a rotating file handler."""
    level = getattr(logging, cfg.level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers if called more than once (e.g. in tests).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if cfg.file:
        log_path = Path(cfg.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=cfg.max_bytes, backupCount=cfg.backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
