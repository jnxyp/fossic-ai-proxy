"""Tests for request injection logic."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from injector import inject
from tests.conftest import make_glossary, make_glossary_loader, make_tenant, make_upstream


@pytest.fixture
def up():
    return make_upstream()


def body(model="model-a", messages=None, **extra):
    return {"model": model, "messages": messages or [{"role": "user", "content": "hello"}], **extra}


# ── model validation ──────────────────────────────────────────────────────────

def test_missing_model_raises_400(up):
    t = make_tenant(up)
    with pytest.raises(HTTPException) as exc:
        inject({"messages": []}, t)
    assert exc.value.status_code == 400


def test_disallowed_model_raises_400(up):
    t = make_tenant(up, allowed_models=["model-a"])
    with pytest.raises(HTTPException) as exc:
        inject(body(model="model-b"), t)
    assert exc.value.status_code == 400


def test_model_not_in_upstream_raises_400(up):
    up2 = make_upstream(models=["model-a"])
    t = make_tenant(up2, allowed_models=["model-z"])
    # Can't happen normally (config validates), but guard test
    t.upstream.available_models = ["model-a"]
    t.allowed_models = ["model-z"]
    with pytest.raises(HTTPException) as exc:
        inject(body(model="model-z"), t)
    assert exc.value.status_code == 400


def test_valid_model_passes(up):
    t = make_tenant(up)
    result = inject(body(), t)
    assert result["model"] == "model-a"


# ── system prompt injection ───────────────────────────────────────────────────

def test_prepends_system_prompt(up):
    t = make_tenant(up, system_prompt="Be helpful.")
    result = inject(body(), t)
    assert result["messages"][0] == {"role": "system", "content": "Be helpful."}


def test_strips_client_system_messages(up):
    t = make_tenant(up)
    b = body(messages=[
        {"role": "system", "content": "client system"},
        {"role": "user", "content": "hi"},
    ])
    result = inject(b, t)
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == t.system_prompt


def test_no_system_prompt_no_injection(up):
    t = make_tenant(up, system_prompt="")
    result = inject(body(), t)
    assert all(m["role"] != "system" for m in result["messages"])


def test_user_messages_preserved(up):
    t = make_tenant(up)
    b = body(messages=[{"role": "user", "content": "translate this"}])
    result = inject(b, t)
    user_msgs = [m for m in result["messages"] if m["role"] == "user"]
    assert user_msgs[0]["content"] == "translate this"


# ── limits ───────────────────────────────────────────────────────────────────

def test_max_user_messages_exceeded(up):
    t = make_tenant(up, max_user_messages=1)
    b = body(messages=[
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ])
    with pytest.raises(HTTPException) as exc:
        inject(b, t)
    assert exc.value.status_code == 400


def test_max_user_messages_exact_limit_passes(up):
    t = make_tenant(up, max_user_messages=2)
    b = body(messages=[
        {"role": "user", "content": "one"},
        {"role": "user", "content": "two"},
    ])
    inject(b, t)  # should not raise


def test_max_chars_exceeded(up):
    t = make_tenant(up, max_chars=5)
    b = body(messages=[{"role": "user", "content": "toolong"}])
    with pytest.raises(HTTPException) as exc:
        inject(b, t)
    assert exc.value.status_code == 400


def test_max_chars_exact_limit_passes(up):
    t = make_tenant(up, max_chars=5)
    b = body(messages=[{"role": "user", "content": "hello"}])
    inject(b, t)  # should not raise


def test_max_chars_counts_all_roles(up):
    t = make_tenant(up, max_chars=10)
    b = body(messages=[
        {"role": "user", "content": "hello"},     # 5
        {"role": "assistant", "content": "world"}, # 5 → total 10
    ])
    inject(b, t)  # should not raise


# ── glossary injection ────────────────────────────────────────────────────────

def test_glossary_injected_after_system_prompt(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(up, glossary=g)
    b = body(messages=[{"role": "user", "content": "Check the flux level."}])
    result = inject(b, t)
    assert result["messages"][0]["role"] == "system"   # main system prompt
    assert result["messages"][1]["role"] == "system"   # glossary
    assert "flux" in result["messages"][1]["content"]


def test_glossary_not_injected_when_no_match(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(up, glossary=g)
    b = body(messages=[{"role": "user", "content": "Tell me about ships."}])
    result = inject(b, t)
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 1  # only the main prompt


def test_no_glossary_no_extra_system_message(up):
    t = make_tenant(up, glossary=None)
    result = inject(body(), t)
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 1


# ── thinking parameter ────────────────────────────────────────────────────────

def test_thinking_anthropic_format_enabled(up):
    t = make_tenant(up)
    b = body(**{"thinking": {"type": "enabled"}})
    result = inject(b, t)
    assert result.get("enable_thinking") is True
    assert "thinking" not in result


def test_thinking_anthropic_format_disabled(up):
    t = make_tenant(up)
    b = body(**{"thinking": {"type": "disabled"}})
    result = inject(b, t)
    assert result.get("enable_thinking") is False
    assert "thinking" not in result


def test_thinking_enable_thinking_passthrough(up):
    t = make_tenant(up)
    b = body(**{"enable_thinking": True})
    result = inject(b, t)
    assert result.get("enable_thinking") is True


def test_thinking_no_param_no_key(up):
    t = make_tenant(up)
    result = inject(body(), t)
    assert "enable_thinking" not in result
    assert "thinking" not in result


def test_thinking_force_off_overrides_client(up):
    t = make_tenant(up, disable_thinking=True)
    b = body(**{"thinking": {"type": "enabled"}})
    result = inject(b, t)
    assert result.get("enable_thinking") is False


def test_thinking_force_on_overrides_client(up):
    t = make_tenant(up, disable_thinking=False)
    b = body(**{"thinking": {"type": "disabled"}})
    result = inject(b, t)
    assert result.get("enable_thinking") is True


# ── other fields passthrough ──────────────────────────────────────────────────

def test_extra_fields_passed_through(up):
    t = make_tenant(up)
    b = body(**{"temperature": 0.7, "max_tokens": 1000})
    result = inject(b, t)
    assert result["temperature"] == 0.7
    assert result["max_tokens"] == 1000


def test_stream_field_preserved(up):
    t = make_tenant(up)
    b = body(**{"stream": True})
    result = inject(b, t)
    assert result["stream"] is True
