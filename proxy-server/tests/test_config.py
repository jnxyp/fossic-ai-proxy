"""Tests for config loading."""
from __future__ import annotations

import sys
import textwrap
import pytest
import config as config_module


def write_config(tmp_path, yaml_text: str):
    f = tmp_path / "config.yaml"
    f.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
    return str(f)


def minimal_config(tmp_path, extra_agent="", extra_tenant="", extra_top=""):
    return write_config(tmp_path, f"""
        {extra_top}
        upstreams:
          - id: up1
            url: http://test/v1/chat/completions
            api_key: key123
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt: "Be helpful."
            {extra_agent}
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: agent1
            {extra_tenant}
    """)


# ── happy path ────────────────────────────────────────────────────────────────

def test_loads_upstream(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert "up1" in cfg.upstreams
    assert cfg.upstreams["up1"].api_key == "key123"


def test_loads_agent(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert "agent1" in cfg.agents
    assert cfg.agents["agent1"].model == "model-a"


def test_loads_tenant_by_key(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert "sk-abc" in cfg.tenants
    assert cfg.tenants["sk-abc"].name == "tenant1"


def test_upstream_attached_to_agent(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    agent = cfg.agents["agent1"]
    assert agent.upstream.id == "up1"
    assert agent.upstream.api_key == "key123"


def test_agent_attached_to_tenant(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    tenant = cfg.tenants["sk-abc"]
    assert tenant.agent.id == "agent1"
    assert tenant.agent.model == "model-a"
    assert tenant.agent.upstream.id == "up1"


def test_multiple_keys_same_tenant(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt: "hello"
        tenants:
          - keys: [sk-key1, sk-key2, sk-key3]
            name: shared
            agent_id: agent1
    """)
    cfg = config_module.load_config(path)
    assert cfg.tenants["sk-key1"].name == "shared"
    assert cfg.tenants["sk-key2"].name == "shared"
    assert cfg.tenants["sk-key3"].name == "shared"
    assert cfg.tenants["sk-key1"] is cfg.tenants["sk-key2"]


def test_log_level_default(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert cfg.log_level == "info"


def test_log_level_custom(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path, extra_top="log_level: debug"))
    assert cfg.log_level == "debug"


def test_extra_body_loaded(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt: "hello"
            extra_body:
              translation_options:
                source_lang: "English"
                target_lang: "Chinese"
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: agent1
    """)
    cfg = config_module.load_config(path)
    assert cfg.agents["agent1"].extra_body == {
        "translation_options": {"source_lang": "English", "target_lang": "Chinese"}
    }


def test_glossary_mode_loaded(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt: "hello"
            glossary_mode: "translation_options"
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: agent1
    """)
    cfg = config_module.load_config(path)
    assert cfg.agents["agent1"].glossary_mode == "translation_options"


def test_glossary_mode_defaults_to_system_message(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert cfg.agents["agent1"].glossary_mode == "system_message"


def test_extra_body_defaults_to_empty(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert cfg.agents["agent1"].extra_body == {}


def test_system_prompt_file(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "test.txt").write_text("Custom prompt content")
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt_file: test.txt
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: agent1
    """)
    original = config_module.PROMPTS_DIR
    config_module.PROMPTS_DIR = tmp_path / "prompts"
    try:
        cfg = config_module.load_config(path)
        assert cfg.agents["agent1"].system_prompt == "Custom prompt content"
    finally:
        config_module.PROMPTS_DIR = original


# ── error cases ───────────────────────────────────────────────────────────────

def test_agent_unknown_upstream_id_exits(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: nonexistent
            model: model-a
            system_prompt: "hello"
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: agent1
    """)
    with pytest.raises(SystemExit):
        config_module.load_config(path)


def test_tenant_unknown_agent_id_exits(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt: "hello"
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: nonexistent
    """)
    with pytest.raises(SystemExit):
        config_module.load_config(path)


def test_no_keys_exits(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt: "hello"
        tenants:
          - keys: []
            name: tenant1
            agent_id: agent1
    """)
    with pytest.raises(SystemExit):
        config_module.load_config(path)


def test_upgrade_agent_loaded(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a, model-b]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt: "hello"
          - id: agent2
            upstream_id: up1
            model: model-b
            system_prompt: "hello"
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: agent1
            upgrade_agent_id: agent2
            upgrade_window: 30
    """)
    cfg = config_module.load_config(path)
    t = cfg.tenants["sk-abc"]
    assert t.upgrade_agent_id == "agent2"
    assert t.upgrade_window == 30
    assert t.upgrade_agent is not None
    assert t.upgrade_agent.id == "agent2"


def test_upgrade_agent_defaults_to_none(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    t = cfg.tenants["sk-abc"]
    assert t.upgrade_agent_id is None
    assert t.upgrade_agent is None
    assert t.upgrade_window == 15


def test_unknown_upgrade_agent_id_exits(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt: "hello"
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: agent1
            upgrade_agent_id: nonexistent
    """)
    with pytest.raises(SystemExit):
        config_module.load_config(path)


def test_missing_prompt_file_exits(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        agents:
          - id: agent1
            upstream_id: up1
            model: model-a
            system_prompt_file: nonexistent.txt
        tenants:
          - keys: [sk-abc]
            name: tenant1
            agent_id: agent1
    """)
    with pytest.raises(SystemExit):
        config_module.load_config(path)
