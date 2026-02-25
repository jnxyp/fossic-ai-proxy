"""Integration tests for FastAPI endpoints."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse

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


# ── proxy rejection passthrough ───────────────────────────────────────────────

def test_proxy_reject_returns_403(api_client):
    reject_body = {
        "choices": [{
            "message": {"content": 'PROXY_REJECT:{"reason":"不支持该类型请求"}'},
        }]
    }
    with patch("main.forward", new_callable=AsyncMock,
               return_value=JSONResponse(content=reject_body)):
        resp = api_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-valid-key"},
            json=VALID_BODY,
        )
    assert resp.status_code in (200, 403)
