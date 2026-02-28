"""Tests for request injection logic."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from injector import inject
from tests.conftest import make_agent, make_glossary_loader, make_tenant, make_upstream


@pytest.fixture
def up():
    return make_upstream()


@pytest.fixture
def ag(up):
    return make_agent(up)


def body(messages=None, **extra):
    return {"messages": messages or [{"role": "user", "content": "hello"}], **extra}


# ── model override ────────────────────────────────────────────────────────────

def test_agent_model_always_used(up, ag):
    t = make_tenant(ag)
    result = inject(body(model="gpt-4o"), t)
    assert result["model"] == "model-a"  # agent model wins


def test_agent_model_used_when_client_omits_model(up, ag):
    t = make_tenant(ag)
    result = inject(body(), t)
    assert result["model"] == "model-a"


# ── system prompt injection ───────────────────────────────────────────────────

def test_prepends_system_prompt(up):
    t = make_tenant(make_agent(up, system_prompt="Be helpful."))
    result = inject(body(), t)
    assert result["messages"][0] == {"role": "system", "content": "Be helpful."}


def test_strips_client_system_messages(up, ag):
    t = make_tenant(ag)
    b = body(messages=[
        {"role": "system", "content": "client system"},
        {"role": "user", "content": "hi"},
    ])
    result = inject(b, t)
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == ag.system_prompt


def test_no_system_prompt_no_injection(up):
    t = make_tenant(make_agent(up, system_prompt=""))
    result = inject(body(), t)
    assert all(m["role"] != "system" for m in result["messages"])


def test_user_messages_preserved(up, ag):
    t = make_tenant(ag)
    b = body(messages=[{"role": "user", "content": "translate this"}])
    result = inject(b, t)
    user_msgs = [m for m in result["messages"] if m["role"] == "user"]
    assert user_msgs[0]["content"] == "translate this"


# ── limits ───────────────────────────────────────────────────────────────────

def test_max_user_messages_exceeded(up, ag):
    t = make_tenant(ag, max_user_messages=1)
    b = body(messages=[
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ])
    with pytest.raises(HTTPException) as exc:
        inject(b, t)
    assert exc.value.status_code == 400


def test_max_user_messages_exact_limit_passes(up, ag):
    t = make_tenant(ag, max_user_messages=2)
    b = body(messages=[
        {"role": "user", "content": "one"},
        {"role": "user", "content": "two"},
    ])
    inject(b, t)  # should not raise


def test_max_chars_exceeded(up, ag):
    t = make_tenant(ag, max_chars=5)
    b = body(messages=[{"role": "user", "content": "toolong"}])
    with pytest.raises(HTTPException) as exc:
        inject(b, t)
    assert exc.value.status_code == 400


def test_max_chars_exact_limit_passes(up, ag):
    t = make_tenant(ag, max_chars=5)
    b = body(messages=[{"role": "user", "content": "hello"}])
    inject(b, t)  # should not raise


def test_max_chars_counts_all_roles(up, ag):
    t = make_tenant(ag, max_chars=10)
    b = body(messages=[
        {"role": "user", "content": "hello"},      # 5
        {"role": "assistant", "content": "world"}, # 5 → total 10
    ])
    inject(b, t)  # should not raise


# ── glossary injection ────────────────────────────────────────────────────────

def test_glossary_merged_into_system_prompt(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(make_agent(up, glossary=g))
    b = body(messages=[{"role": "user", "content": "Check the flux level."}])
    result = inject(b, t)
    # system_prompt and glossary merged into a single system message
    assert result["messages"][0]["role"] == "system"
    assert result["messages"][1]["role"] == "user"
    assert "You are a translator" in result["messages"][0]["content"]
    assert "flux" in result["messages"][0]["content"]


def test_glossary_not_injected_when_no_match(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(make_agent(up, glossary=g))
    b = body(messages=[{"role": "user", "content": "Tell me about ships."}])
    result = inject(b, t)
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 1  # only the main prompt


def test_no_glossary_no_extra_system_message(up, ag):
    t = make_tenant(ag)
    result = inject(body(), t)
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 1


# ── glossary_mode: translation_options ───────────────────────────────────────

def test_glossary_mode_translation_options_adds_terms(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(make_agent(up, glossary=g, glossary_mode="translation_options",
                               extra_body={"translation_options": {"source_lang": "English", "target_lang": "Chinese"}}))
    b = body(messages=[{"role": "user", "content": "Check the flux level."}])
    result = inject(b, t)
    terms = result["translation_options"]["terms"]
    assert any(entry["source"] == "flux" and entry["target"] == "幅能" for entry in terms)


def test_glossary_mode_translation_options_no_match_no_terms(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(make_agent(up, glossary=g, glossary_mode="translation_options",
                               extra_body={"translation_options": {"source_lang": "English", "target_lang": "Chinese"}}))
    b = body(messages=[{"role": "user", "content": "Tell me about ships."}])
    result = inject(b, t)
    assert "terms" not in result.get("translation_options", {})


def test_glossary_mode_translation_options_no_system_message(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(make_agent(up, glossary=g, glossary_mode="translation_options"))
    b = body(messages=[{"role": "user", "content": "Check the flux level."}])
    result = inject(b, t)
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    # only the main system prompt, no glossary system message
    assert len(system_msgs) == 1


def test_glossary_mode_translation_options_includes_alternatives(up):
    from glossary import Glossary, GlossaryTerm
    from tests.conftest import _TestGlossaryLoader
    term = GlossaryTerm(english="flux", chinese="幅能", notes="", alternatives=["flux level"])
    g = _TestGlossaryLoader(Glossary([term]))
    t = make_tenant(make_agent(up, glossary=g, glossary_mode="translation_options",
                               extra_body={"translation_options": {}}))
    b = body(messages=[{"role": "user", "content": "flux level"}])
    result = inject(b, t)
    terms = result["translation_options"]["terms"]
    sources = [e["source"] for e in terms]
    assert "flux" in sources
    assert "flux level" in sources


# ── system_prompt_position: user_prefix ──────────────────────────────────────

def test_user_prefix_prepends_system_prompt_to_user_message(up):
    t = make_tenant(make_agent(up, system_prompt="[SYS] Be helpful.",
                               system_prompt_position="user_prefix"))
    b = body(messages=[{"role": "user", "content": "translate this"}])
    result = inject(b, t)
    user_msgs = [m for m in result["messages"] if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"].startswith("[SYS] Be helpful.")
    assert "translate this" in user_msgs[0]["content"]


def test_user_prefix_no_system_messages(up):
    t = make_tenant(make_agent(up, system_prompt="[PROMPT]",
                               system_prompt_position="user_prefix"))
    b = body(messages=[{"role": "user", "content": "hello"}])
    result = inject(b, t)
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 0


def test_user_prefix_glossary_appended_to_prefix(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(make_agent(up, system_prompt="[SYS]", glossary=g,
                               system_prompt_position="user_prefix"))
    b = body(messages=[{"role": "user", "content": "Check the flux level."}])
    result = inject(b, t)
    user_msgs = [m for m in result["messages"] if m["role"] == "user"]
    assert len(user_msgs) == 1
    content = user_msgs[0]["content"]
    assert content.startswith("[SYS]")
    assert "flux" in content
    assert "幅能" in content


def test_user_prefix_no_glossary_no_extra_content(up):
    g = make_glossary_loader(("flux", "幅能", ""))
    t = make_tenant(make_agent(up, system_prompt="[SYS]", glossary=g,
                               system_prompt_position="user_prefix"))
    b = body(messages=[{"role": "user", "content": "Tell me about ships."}])
    result = inject(b, t)
    user_msgs = [m for m in result["messages"] if m["role"] == "user"]
    assert user_msgs[0]["content"].startswith("[SYS]\n\n")  # only prefix, no glossary
    assert "Tell me about ships." in user_msgs[0]["content"]


def test_user_prefix_no_translation_options_injected(up):
    t = make_tenant(make_agent(up, system_prompt="[SYS]",
                               system_prompt_position="user_prefix",
                               extra_body={}))
    b = body(messages=[{"role": "user", "content": "hello"}])
    result = inject(b, t)
    assert "translation_options" not in result


def test_user_prefix_fallback_when_no_user_message(up):
    t = make_tenant(make_agent(up, system_prompt="[SYS]",
                               system_prompt_position="user_prefix"))
    b = body(messages=[{"role": "assistant", "content": "previous response"}])
    result = inject(b, t)
    # Fallback: insert as system message when no user message found
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == "[SYS]"


def test_user_prefix_e2e_with_glossary(up):
    """End-to-end test: system_prompt_position=user_prefix with glossary."""
    g = make_glossary_loader(("flux", "幅能", ""))
    ag = make_agent(
        up,
        system_prompt="[PROMPT]",
        system_prompt_position="user_prefix",
        glossary=g
    )
    t = make_tenant(ag)
    b = body(messages=[{"role": "user", "content": "Check the flux level"}])
    result = inject(b, t)

    # No system messages should exist
    system_msgs = [m for m in result["messages"] if m["role"] == "system"]
    assert len(system_msgs) == 0, f"Expected no system messages, got: {system_msgs}"

    # Single user message with prepended prompt
    user_msgs = [m for m in result["messages"] if m["role"] == "user"]
    assert len(user_msgs) == 1
    content = user_msgs[0]["content"]

    # Content should start with prompt, contain glossary, then user input
    assert content.startswith("[PROMPT]"), f"Content should start with prompt: {content[:50]}"
    assert "幅能" in content, f"Content should contain glossary translation: {content}"
    assert "Check the flux level" in content, f"Content should contain user input: {content}"


# ── extra_body ────────────────────────────────────────────────────────────────

def test_extra_body_merged_into_result(up):
    t = make_tenant(make_agent(up, extra_body={"translation_options": {"source_lang": "English"}}))
    result = inject(body(), t)
    assert result["translation_options"] == {"source_lang": "English"}


def test_extra_body_agent_wins_over_client(up):
    t = make_tenant(make_agent(up, extra_body={"temperature": 0.1}))
    result = inject(body(**{"temperature": 0.9}), t)
    assert result["temperature"] == 0.1  # agent wins


def test_no_extra_body_no_extra_fields(up, ag):
    result = inject(body(), make_tenant(ag))
    assert "translation_options" not in result


# ── thinking parameter ────────────────────────────────────────────────────────

def test_thinking_anthropic_format_enabled(up, ag):
    t = make_tenant(ag)
    b = body(**{"thinking": {"type": "enabled"}})
    result = inject(b, t)
    assert result.get("enable_thinking") is True
    assert "thinking" not in result


def test_thinking_anthropic_format_disabled(up, ag):
    t = make_tenant(ag)
    b = body(**{"thinking": {"type": "disabled"}})
    result = inject(b, t)
    assert result.get("enable_thinking") is False
    assert "thinking" not in result


def test_thinking_enable_thinking_passthrough(up, ag):
    t = make_tenant(ag)
    b = body(**{"enable_thinking": True})
    result = inject(b, t)
    assert result.get("enable_thinking") is True


def test_thinking_no_param_no_key(up, ag):
    t = make_tenant(ag)
    result = inject(body(), t)
    assert "enable_thinking" not in result
    assert "thinking" not in result


def test_thinking_force_off_overrides_client(up):
    t = make_tenant(make_agent(up, enable_thinking=False))
    b = body(**{"thinking": {"type": "enabled"}})
    result = inject(b, t)
    assert result.get("enable_thinking") is False


def test_thinking_force_on_overrides_client(up):
    t = make_tenant(make_agent(up, enable_thinking=True))
    b = body(**{"thinking": {"type": "disabled"}})
    result = inject(b, t)
    assert result.get("enable_thinking") is True


# ── other fields passthrough ──────────────────────────────────────────────────

def test_extra_fields_passed_through(up, ag):
    t = make_tenant(ag)
    b = body(**{"temperature": 0.7, "max_tokens": 1000})
    result = inject(b, t)
    assert result["temperature"] == 0.7
    assert result["max_tokens"] == 1000


def test_stream_field_preserved(up, ag):
    t = make_tenant(ag)
    b = body(**{"stream": True})
    result = inject(b, t)
    assert result["stream"] is True
