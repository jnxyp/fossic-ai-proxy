"""Shared fixtures for all tests."""
from __future__ import annotations

import pytest
from fastapi.responses import JSONResponse
from unittest.mock import patch
from fastapi.testclient import TestClient

from config import AppConfig, TenantConfig, UpstreamConfig
from glossary import Glossary, GlossaryLoader, GlossaryTerm


# ── helpers ──────────────────────────────────────────────────────────────────

def make_upstream(id="test-upstream", models=None) -> UpstreamConfig:
    return UpstreamConfig(
        id=id,
        url="http://test-upstream/v1/chat/completions",
        api_key="upstream-key-123",
        available_models=models or ["model-a", "model-b"],
    )


def make_tenant(upstream: UpstreamConfig, **kwargs) -> TenantConfig:
    defaults = dict(
        name="test-tenant",
        upstream_id=upstream.id,
        allowed_models=["model-a"],
        system_prompt="You are a translator.",
        cors_origins=["https://example.com"],
        allowed_referers=[],
        max_user_messages=None,
        max_chars=None,
        disable_thinking=None,
        glossary=None,
    )
    defaults.update(kwargs)
    t = TenantConfig(**defaults)
    t.upstream = upstream
    return t


def make_glossary(*pairs: tuple[str, str, str]) -> Glossary:
    """pairs: (english, chinese, notes)"""
    return Glossary([
        GlossaryTerm(english=e, chinese=c, notes=n)
        for e, c, n in pairs
    ])


class _TestGlossaryLoader:
    """In-memory GlossaryLoader-compatible wrapper for tests."""
    def __init__(self, glossary: Glossary):
        self._g = glossary

    def find_matches(self, text: str) -> list[GlossaryTerm]:
        return self._g.find_matches(text)

    def build_system_message(self, matches: list[GlossaryTerm]) -> str:
        return self._g.build_system_message(matches)


def make_glossary_loader(*pairs: tuple[str, str, str]) -> _TestGlossaryLoader:
    """Return a GlossaryLoader-compatible object backed by in-memory terms."""
    return _TestGlossaryLoader(make_glossary(*pairs))


MOCK_RESPONSE_DATA = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "model-a",
    "choices": [{
        "index": 0,
        "message": {"role": "assistant", "content": "Translation result"},
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
}


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def upstream():
    return make_upstream()


@pytest.fixture
def tenant(upstream):
    return make_tenant(upstream)


@pytest.fixture
def app_cfg(upstream, tenant):
    return AppConfig(
        upstreams={upstream.id: upstream},
        tenants={"sk-valid-key": tenant},
        log_level="info",
    )


@pytest.fixture
def api_client(app_cfg, tmp_path):
    """FastAPI TestClient with mocked config and DB."""
    import main
    db_path = tmp_path / "usage.db"
    with patch("main.load_config", return_value=app_cfg), \
         patch("db.DB_PATH", db_path):
        with TestClient(main.app) as c:
            yield c
