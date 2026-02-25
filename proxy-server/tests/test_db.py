"""Tests for SQLite usage logging."""
from __future__ import annotations

import sqlite3

import pytest
import db as db_module


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "usage.db")
    db_module.init_db()


def query_all():
    with sqlite3.connect(db_module.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM requests ORDER BY id").fetchall()


# ── init ──────────────────────────────────────────────────────────────────────

def test_init_creates_table():
    rows = query_all()
    assert rows == []


def test_init_idempotent():
    db_module.init_db()  # second call should not raise
    db_module.init_db()
    rows = query_all()
    assert rows == []


# ── log_request ───────────────────────────────────────────────────────────────

def test_log_writes_row():
    db_module.log_request("tenant-a", "sk-ABCDEFGH", "model-a", False, 100, 200, 350, 200)
    rows = query_all()
    assert len(rows) == 1


def test_log_fields_stored_correctly():
    db_module.log_request("tenant-a", "sk-ABCDEFGH", "model-a", False, 100, 250, 420, 200)
    row = query_all()[0]
    assert row["tenant"] == "tenant-a"
    assert row["model"] == "model-a"
    assert row["stream"] == 0
    assert row["input_chars"] == 100
    assert row["output_chars"] == 250
    assert row["elapsed_ms"] == 420
    assert row["status"] == 200


def test_log_stream_flag():
    db_module.log_request("t", "sk-12345678", "m", True, 50, 80, 1500, 200)
    row = query_all()[0]
    assert row["stream"] == 1


def test_log_null_output_chars():
    db_module.log_request("t", "sk-12345678", "m", True, 50, None, 1500, 200)
    row = query_all()[0]
    assert row["output_chars"] is None


def test_key_hint_last_8_chars():
    db_module.log_request("t", "sk-ABCDEFGH1234", "m", False, 0, 0, 0, 200)
    row = query_all()[0]
    assert row["key_hint"] == "...EFGH1234"


def test_key_hint_does_not_store_full_key():
    db_module.log_request("t", "sk-supersecretkey", "m", False, 0, 0, 0, 200)
    row = query_all()[0]
    assert "supersecret" not in row["key_hint"]


def test_log_error_status():
    db_module.log_request("t", "sk-12345678", "m", False, 100, None, 50, 400)
    row = query_all()[0]
    assert row["status"] == 400


def test_multiple_entries_ordered():
    db_module.log_request("a", "sk-00000001", "m", False, 10, 20, 100, 200)
    db_module.log_request("b", "sk-00000002", "m", False, 30, 40, 200, 200)
    db_module.log_request("c", "sk-00000003", "m", False, 50, 60, 300, 200)
    rows = query_all()
    assert len(rows) == 3
    assert [r["tenant"] for r in rows] == ["a", "b", "c"]


def test_ts_is_recorded():
    db_module.log_request("t", "sk-12345678", "m", False, 0, 0, 0, 200)
    row = query_all()[0]
    assert row["ts"] is not None
    assert len(row["ts"]) > 0
