"""Logging configuration service."""

import logging
from logging.handlers import RotatingFileHandler

from questlog.config import QuestlogConfig


def setup_logging(cfg: QuestlogConfig) -> None:
    """Configure logging for the application.

    Args:
        cfg: Configuration object with logging settings.
    """
    logger = logging.getLogger("questlog")
    logger.setLevel(logging.INFO)
    # Avoid duplicate handlers if setup_logging is called multiple times
    if logger.handlers:
        logger.handlers.clear()
    logger.propagate = False
    handler = RotatingFileHandler(
        cfg.logfile,
        maxBytes=cfg.log_max_bytes,
        backupCount=cfg.log_backups,
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

