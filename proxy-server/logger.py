from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_LOG_NAME = "fossic-ai-proxy"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        try:
            msg_value = json.loads(msg)
        except (json.JSONDecodeError, ValueError):
            msg_value = msg

        return json.dumps({
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
                         .strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "msg": msg_value,
        }, ensure_ascii=False)


def _setup() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logger = logging.getLogger(_LOG_NAME)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


_logger = _setup()


def get_logger() -> logging.Logger:
    return _logger


def set_level(level: str) -> None:
    _logger.setLevel(level.upper())
