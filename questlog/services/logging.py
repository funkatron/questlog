"""Logging configuration service."""

import logging
from logging.handlers import RotatingFileHandler

from questlog.config import QuestlogConfig


def setup_logging(cfg: QuestlogConfig, debug: bool = False) -> None:
    """Configure logging for the application.

    Args:
        cfg: Configuration object with logging settings.
        debug: If True, enable DEBUG level logging.
    """
    logger = logging.getLogger("questlog")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
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

    # Also add console handler for debug mode
    if debug:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

