"""Integration tests for FastAPI endpoints."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from config import AppConfig
from tests.conftest import MOCK_RESPONSE_DATA, make_agent, make_tenant, make_upstream


VALID_BODY = {
    "model": "model-a",
    "messages": [{"role": "user", "content": "Translate this."}],
}


@pytest.fixture
def mock_forward():
    """Patch proxy.forward to return a standard JSON response."""
    with patch("main.forward", new_callable=AsyncMock,
               return_value=JSONResponse(content=MOCK_RESPONSE_DATA)) as m:
        yield m


# ── auth ──────────────────────────────────────────────────────────────────────

def test_valid_key_returns_200(api_client, mock_forward):
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key"},
        json=VALID_BODY,
    )
    assert resp.status_code == 200


def test_invalid_key_returns_401(api_client):
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-wrong-key"},
        json=VALID_BODY,
    )
    assert resp.status_code == 401


def test_missing_auth_returns_403(api_client):
    resp = api_client.post("/v1/chat/completions", json=VALID_BODY)
    assert resp.status_code in (401, 403)


# ── referer ───────────────────────────────────────────────────────────────────

def test_allowed_referer_passes(api_client, app_cfg, upstream, mock_forward):
    t = make_tenant(make_agent(upstream), allowed_referers=["https://example.com/"])
    app_cfg.tenants["sk-valid-key"] = t
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key", "Referer": "https://example.com/page"},
        json=VALID_BODY,
    )
    assert resp.status_code == 200


def test_blocked_referer_returns_403(api_client, app_cfg, upstream):
    t = make_tenant(make_agent(upstream), allowed_referers=["https://example.com/"])
    app_cfg.tenants["sk-valid-key"] = t
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key", "Referer": "https://evil.com/"},
        json=VALID_BODY,
    )
    assert resp.status_code == 403


def test_no_referer_blocked_when_referer_required(api_client, app_cfg, upstream):
    t = make_tenant(make_agent(upstream), allowed_referers=["https://example.com/"])
    app_cfg.tenants["sk-valid-key"] = t
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key"},
        json=VALID_BODY,
    )
    assert resp.status_code == 403


def test_no_referer_restriction_passes_without_referer(api_client, mock_forward):
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key"},
        json=VALID_BODY,
    )
    assert resp.status_code == 200


# ── request validation ────────────────────────────────────────────────────────

def test_no_model_field_still_succeeds(api_client, mock_forward):
    """Agent provides model, so client doesn't need to send it."""
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200


def test_wrong_model_overridden_by_agent(api_client, mock_forward):
    """Client's model is ignored; agent model is always used."""
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key"},
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200


def test_too_many_user_messages_returns_400(api_client, app_cfg, upstream):
    t = make_tenant(make_agent(upstream), max_user_messages=1)
    app_cfg.tenants["sk-valid-key"] = t
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key"},
        json={
            "model": "model-a",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "user", "content": "second"},
            ],
        },
    )
    assert resp.status_code == 400


def test_too_many_chars_returns_400(api_client, app_cfg, upstream):
    t = make_tenant(make_agent(upstream), max_chars=5)
    app_cfg.tenants["sk-valid-key"] = t
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key"},
        json={"model": "model-a", "messages": [{"role": "user", "content": "this is too long"}]},
    )
    assert resp.status_code == 400


# ── CORS preflight ────────────────────────────────────────────────────────────

def test_options_allowed_origin_returns_204(api_client):
    resp = api_client.options(
        "/v1/chat/completions",
        headers={"Origin": "https://example.com"},
    )
    assert resp.status_code == 204
    assert resp.headers.get("access-control-allow-origin") == "https://example.com"


def test_options_disallowed_origin_returns_403(api_client):
    resp = api_client.options(
        "/v1/chat/completions",
        headers={"Origin": "https://evil.com"},
    )
    assert resp.status_code == 403


def test_options_no_origin_returns_403(api_client):
    resp = api_client.options("/v1/chat/completions")
    assert resp.status_code == 403


# ── CORS response headers ─────────────────────────────────────────────────────

def test_cors_headers_on_valid_response(api_client, mock_forward):
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key", "Origin": "https://example.com"},
        json=VALID_BODY,
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://example.com"


def test_no_cors_headers_for_disallowed_origin(api_client, mock_forward):
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key", "Origin": "https://evil.com"},
        json=VALID_BODY,
    )
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.parametrize("length,status", [(7018, 200), (10000, 200), (10001, 400)])
def test_translation_length_boundary(api_client, app_cfg, mock_forward, length, status):
    app_cfg.tenants["sk-valid-key"].max_chars = 10000
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key", "Origin": "https://example.com"},
        json={"messages": [{"role": "user", "content": "中" * length}]},
    )
    assert resp.status_code == status
    assert resp.headers["access-control-allow-origin"] == "https://example.com"
    if status == 400:
        assert resp.json()["detail"] == "Request too long: 10001 chars (max 10000)."
        mock_forward.assert_not_called()
    else:
        mock_forward.assert_awaited_once()


@pytest.mark.parametrize("authorization", [None, "Bearer sk-wrong-key"])
@pytest.mark.parametrize("origin", ["https://example.com", "https://evil.com"])
def test_auth_error_cors(api_client, authorization, origin):
    headers = {"Origin": origin}
    if authorization:
        headers["Authorization"] = authorization
    resp = api_client.post("/v1/chat/completions", headers=headers, json=VALID_BODY)
    assert resp.status_code in (401, 403)
    assert resp.headers.get("access-control-allow-origin") == (
        origin if origin == "https://example.com" else None
    )


def test_referer_error_cors(api_client, app_cfg):
    app_cfg.tenants["sk-valid-key"].allowed_referers = ["https://example.com/"]
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key", "Origin": "https://example.com"},
        json=VALID_BODY,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Referer not allowed."
    assert resp.headers["access-control-allow-origin"] == "https://example.com"


@pytest.mark.parametrize("error,status", [
    (HTTPException(502, "Upstream failed", headers={"Retry-After": "3"}), 502),
    (RequestValidationError([]), 422),
    (RuntimeError("private internal details"), 500),
])
@pytest.mark.parametrize("origin", ["https://example.com", "https://evil.com"])
def test_error_responses_cors(api_client, mock_forward, error, status, origin):
    import main

    mock_forward.side_effect = error
    # Keep the fixture lifespan/config, but inspect 500 responses instead of re-raising.
    with TestClient(main.app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-valid-key", "Origin": origin},
            json=VALID_BODY,
        )
    assert resp.status_code == status
    assert resp.headers.get("access-control-allow-origin") == (
        origin if origin == "https://example.com" else None
    )
    if status == 502:
        assert resp.headers["retry-after"] == "3"
        assert resp.json()["detail"] == "Upstream failed"
    if status == 500:
        assert resp.json() == {"detail": "Internal Server Error"}


def test_error_cors_does_not_use_another_tenants_allowlist(api_client, app_cfg, upstream):
    app_cfg.tenants["sk-other-key"] = make_tenant(
        make_agent(upstream), cors_origins=["https://other.example.com"],
    )
    app_cfg.tenants["sk-valid-key"].max_chars = 1
    resp = api_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-valid-key", "Origin": "https://other.example.com"},
        json=VALID_BODY,
    )
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers

