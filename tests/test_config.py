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


def minimal_config(tmp_path, extra_tenant="", extra_top=""):
    return write_config(tmp_path, f"""
        {extra_top}
        upstreams:
          - id: up1
            url: http://test/v1/chat/completions
            api_key: key123
            available_models: [model-a]
        tenants:
          - keys: [sk-abc]
            name: tenant1
            upstream_id: up1
            allowed_models: [model-a]
            system_prompt: "Be helpful."
        {extra_tenant}
    """)


# ── happy path ────────────────────────────────────────────────────────────────

def test_loads_upstream(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert "up1" in cfg.upstreams
    assert cfg.upstreams["up1"].api_key == "key123"


def test_loads_tenant_by_key(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert "sk-abc" in cfg.tenants
    assert cfg.tenants["sk-abc"].name == "tenant1"


def test_upstream_attached_to_tenant(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    tenant = cfg.tenants["sk-abc"]
    assert tenant.upstream.id == "up1"
    assert tenant.upstream.api_key == "key123"


def test_multiple_keys_same_tenant(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        tenants:
          - keys: [sk-key1, sk-key2, sk-key3]
            name: shared
            upstream_id: up1
            allowed_models: [model-a]
            system_prompt: "hello"
    """)
    cfg = config_module.load_config(path)
    assert cfg.tenants["sk-key1"].name == "shared"
    assert cfg.tenants["sk-key2"].name == "shared"
    assert cfg.tenants["sk-key3"].name == "shared"
    # All keys map to the same object
    assert cfg.tenants["sk-key1"] is cfg.tenants["sk-key2"]


def test_log_level_default(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path))
    assert cfg.log_level == "info"


def test_log_level_custom(tmp_path):
    cfg = config_module.load_config(minimal_config(tmp_path, extra_top="log_level: debug"))
    assert cfg.log_level == "debug"


def test_empty_allowed_models_allows_all_upstream_models(tmp_path):
    """allowed_models: [] means tenant can use all upstream models."""
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a, model-b]
        tenants:
          - keys: [sk-abc]
            name: tenant1
            upstream_id: up1
            allowed_models: []
            system_prompt: "hello"
    """)
    cfg = config_module.load_config(path)
    assert cfg.tenants["sk-abc"].allowed_models == []


def test_system_prompt_file(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "test.txt").write_text("Custom prompt content")
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        tenants:
          - keys: [sk-abc]
            name: tenant1
            upstream_id: up1
            allowed_models: [model-a]
            system_prompt_file: test.txt
    """)
    original = config_module.PROMPTS_DIR
    config_module.PROMPTS_DIR = tmp_path / "prompts"
    try:
        cfg = config_module.load_config(path)
        assert cfg.tenants["sk-abc"].system_prompt == "Custom prompt content"
    finally:
        config_module.PROMPTS_DIR = original


# ── error cases ───────────────────────────────────────────────────────────────

def test_unknown_upstream_id_exits(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        tenants:
          - keys: [sk-abc]
            name: tenant1
            upstream_id: nonexistent
            allowed_models: [model-a]
            system_prompt: "hello"
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
        tenants:
          - keys: []
            name: tenant1
            upstream_id: up1
            allowed_models: [model-a]
            system_prompt: "hello"
    """)
    with pytest.raises(SystemExit):
        config_module.load_config(path)


def test_invalid_allowed_models_exits(tmp_path):
    path = write_config(tmp_path, """
        upstreams:
          - id: up1
            url: http://test
            api_key: key
            available_models: [model-a]
        tenants:
          - keys: [sk-abc]
            name: tenant1
            upstream_id: up1
            allowed_models: [model-z]
            system_prompt: "hello"
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
        tenants:
          - keys: [sk-abc]
            name: tenant1
            upstream_id: up1
            allowed_models: [model-a]
            system_prompt_file: nonexistent.txt
    """)
    with pytest.raises(SystemExit):
        config_module.load_config(path)
