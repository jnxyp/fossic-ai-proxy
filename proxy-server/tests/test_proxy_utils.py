"""Tests for proxy.py utility functions and rejection detection."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from proxy import _parse_sse_content, REJECT_MARKER
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


# ── non-stream rejection detection ───────────────────────────────────────────

def _mock_httpx_client(response_data: dict, status: int = 200):
    """Return a context-manager-compatible mock for httpx.AsyncClient."""
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.json = MagicMock(return_value=response_data)
    mock_resp.text = json.dumps(response_data)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)
    return mock_client


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_non_stream_returns_json_response():
    from proxy import _non_stream
    data = {"choices": [{"message": {"content": "Normal translation"}}]}
    with patch("proxy.httpx.AsyncClient", return_value=_mock_httpx_client(data)):
        result = run(_non_stream("http://test", {}, {}))
    assert isinstance(result, JSONResponse)


def test_non_stream_rejection_raises_403():
    from proxy import _non_stream
    data = {"choices": [{"message": {"content": f'{REJECT_MARKER}{{"reason":"不支持该请求"}}'}}]}
    with patch("proxy.httpx.AsyncClient", return_value=_mock_httpx_client(data)):
        with pytest.raises(HTTPException) as exc:
            run(_non_stream("http://test", {}, {}))
    assert exc.value.status_code == 403
    assert "不支持该请求" in exc.value.detail


def test_non_stream_rejection_malformed_json_still_403():
    from proxy import _non_stream
    data = {"choices": [{"message": {"content": f"{REJECT_MARKER}not-json"}}]}
    with patch("proxy.httpx.AsyncClient", return_value=_mock_httpx_client(data)):
        with pytest.raises(HTTPException) as exc:
            run(_non_stream("http://test", {}, {}))
    assert exc.value.status_code == 403


def test_non_stream_upstream_error_raises_with_status():
    from proxy import _non_stream
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "rate limited"
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("proxy.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc:
            run(_non_stream("http://test", {}, {}))
    assert exc.value.status_code == 429
