"""Repeat-request detection for automatic agent upgrade."""
from __future__ import annotations

import hashlib
import json
import time
from threading import Lock

_cache: dict[tuple, float] = {}
_lock = Lock()


def _messages_hash(messages: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(messages, ensure_ascii=False).encode()
    ).hexdigest()


def check_and_record(api_key: str, messages: list[dict], window: int, client_ip: str | None = None) -> bool:
    """Return True if an identical request was seen from this key within window seconds.

    Always records the current request (updating the timestamp), so consecutive
    repeats stay upgraded as long as they keep arriving within the window.
    If client_ip is provided, it is included in the cache key to isolate users
    sharing the same API key.
    """
    key = (api_key, client_ip, _messages_hash(messages))
    now = time.monotonic()
    with _lock:
        last = _cache.get(key)
        is_repeat = last is not None and (now - last) < window
        _cache[key] = now
        expired = [k for k, t in _cache.items() if now - t >= window]
        for k in expired:
            del _cache[k]
    return is_repeat
