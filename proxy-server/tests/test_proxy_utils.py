"""Tests for proxy.py utility functions."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from proxy import _parse_sse_content
from tests.conftest import make_tenant, make_upstream


# ── _parse_sse_content ────────────────────────────────────────────────────────

def sse(content: str) -> bytes:
    data = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(data)}\n\n".encode()


def test_parse_basic_content():
    assert _parse_sse_content(sse("hello")) == "hello"


def test_parse_done_chunk():
    assert _parse_sse_content(b"data: [DONE]\n\n") == ""


def test_parse_empty_delta_role_only():
    chunk = b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
    assert _parse_sse_content(chunk) == ""


def test_parse_null_content():
    chunk = b'data: {"choices":[{"delta":{"content":null}}]}\n\n'
    assert _parse_sse_content(chunk) == ""


def test_parse_multiple_events_in_chunk():
    chunk = sse("foo") + sse("bar")
    assert _parse_sse_content(chunk) == "foobar"


def test_parse_malformed_json_ignored():
    chunk = b"data: not-json\n\ndata: [DONE]\n\n"
    assert _parse_sse_content(chunk) == ""


def test_parse_mixed_valid_invalid():
    chunk = b"data: bad-json\n\n" + sse("valid")
    assert _parse_sse_content(chunk) == "valid"


def test_parse_chinese_content():
    assert _parse_sse_content(sse("幅能危急")) == "幅能危急"


def test_parse_empty_chunk():
    assert _parse_sse_content(b"") == ""


