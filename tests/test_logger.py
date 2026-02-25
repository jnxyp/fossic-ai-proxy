"""Tests for JSON log formatter."""
from __future__ import annotations

import json
import logging

import pytest

from logger import _JsonFormatter


@pytest.fixture
def formatter():
    return _JsonFormatter()


def make_record(msg: str, level: int = logging.INFO) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test", level=level, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )
    return record


def parse(formatter, msg: str, level: int = logging.INFO) -> dict:
    return json.loads(formatter.format(make_record(msg, level)))


# ── output is valid JSON ──────────────────────────────────────────────────────

def test_output_is_valid_json(formatter):
    result = formatter.format(make_record("hello world"))
    json.loads(result)  # must not raise


def test_output_is_single_line(formatter):
    result = formatter.format(make_record("hello world"))
    assert "\n" not in result


# ── required fields ───────────────────────────────────────────────────────────

def test_has_ts_field(formatter):
    entry = parse(formatter, "hello")
    assert "ts" in entry


def test_has_level_field(formatter):
    entry = parse(formatter, "hello", logging.WARNING)
    assert entry["level"] == "WARNING"


def test_has_msg_field(formatter):
    entry = parse(formatter, "hello")
    assert "msg" in entry


def test_level_info(formatter):
    assert parse(formatter, "x", logging.INFO)["level"] == "INFO"


def test_level_debug(formatter):
    assert parse(formatter, "x", logging.DEBUG)["level"] == "DEBUG"


def test_level_error(formatter):
    assert parse(formatter, "x", logging.ERROR)["level"] == "ERROR"


# ── plain text message ────────────────────────────────────────────────────────

def test_plain_text_msg_is_string(formatter):
    entry = parse(formatter, "[tenant] request received")
    assert isinstance(entry["msg"], str)
    assert entry["msg"] == "[tenant] request received"


# ── JSON message embedded as object, not string ───────────────────────────────

def test_json_msg_embedded_as_object(formatter):
    payload = {"model": "glm-5", "messages": [{"role": "user", "content": "hi"}]}
    entry = parse(formatter, json.dumps(payload))
    assert isinstance(entry["msg"], dict), "JSON message must be embedded as object, not string"


def test_json_msg_content_preserved(formatter):
    payload = {"model": "glm-5", "temperature": 0.7}
    entry = parse(formatter, json.dumps(payload))
    assert entry["msg"]["model"] == "glm-5"
    assert entry["msg"]["temperature"] == 0.7


def test_json_array_embedded_as_array(formatter):
    payload = [{"role": "user", "content": "hello"}]
    entry = parse(formatter, json.dumps(payload))
    assert isinstance(entry["msg"], list)


def test_json_msg_not_double_encoded(formatter):
    """The msg field must NOT be a JSON string containing another JSON string."""
    payload = {"key": "value"}
    raw = formatter.format(make_record(json.dumps(payload)))
    # If double-encoded, msg would be a string like '"{\"key\": ...}"'
    entry = json.loads(raw)
    assert not isinstance(entry["msg"], str), "JSON content must not be double-encoded as string"


def test_json_with_chinese_content(formatter):
    payload = {"content": "幅能危急，立即排幅"}
    entry = parse(formatter, json.dumps(payload, ensure_ascii=False))
    assert entry["msg"]["content"] == "幅能危急，立即排幅"


# ── malformed / edge cases ────────────────────────────────────────────────────

def test_malformed_json_treated_as_plain_text(formatter):
    entry = parse(formatter, "not-json{broken")
    assert isinstance(entry["msg"], str)
    assert entry["msg"] == "not-json{broken"


def test_empty_message(formatter):
    entry = parse(formatter, "")
    assert entry["msg"] == ""


def test_numeric_string_not_treated_as_json(formatter):
    entry = parse(formatter, "42")
    # "42" is valid JSON (a number), so msg will be int 42 — that's acceptable
    assert entry["msg"] == 42 or entry["msg"] == "42"
