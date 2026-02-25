from __future__ import annotations

import logging

_LOG_NAME = "fossic-ai-proxy"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOG_NAME)


def set_level(level: str) -> None:
    logging.getLogger(_LOG_NAME).setLevel(level.upper())
