from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/usage.db")
_lock = threading.Lock()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           TEXT    NOT NULL,
                tenant       TEXT    NOT NULL,
                key_hint     TEXT    NOT NULL,
                model        TEXT,
                stream       INTEGER,
                input_chars  INTEGER,
                output_chars INTEGER,
                elapsed_ms   INTEGER,
                status       INTEGER
            )
        """)
        conn.commit()


def log_request(
    tenant: str,
    key: str,
    model: str,
    stream: bool,
    input_chars: int,
    output_chars: int | None,
    elapsed_ms: int,
    status: int,
):
    key_hint = "..." + key[-8:]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """INSERT INTO requests
                   (ts, tenant, key_hint, model, stream, input_chars, output_chars, elapsed_ms, status)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ts, tenant, key_hint, model, int(stream), input_chars, output_chars, elapsed_ms, status),
            )
            conn.commit()
