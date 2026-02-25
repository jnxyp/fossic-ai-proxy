from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from glossary import Glossary, load_glossary_csv

PROMPTS_DIR = Path("prompts")


@dataclass
class UpstreamConfig:
    id: str
    url: str
    api_key: str
    available_models: list[str]


@dataclass
class TenantConfig:
    name: str
    upstream_id: str
    allowed_models: list[str]
    system_prompt: str
    cors_origins: list[str] = field(default_factory=list)
    allowed_referers: list[str] = field(default_factory=list)
    max_user_messages: Optional[int] = None
    max_chars: Optional[int] = None
    disable_thinking: Optional[bool] = None
    glossary: Optional[Glossary] = None
    upstream: UpstreamConfig = field(init=False)


@dataclass
class AppConfig:
    upstreams: dict[str, UpstreamConfig]
    tenants: dict[str, TenantConfig]  # key -> TenantConfig


def _load_glossary(u: dict, name: str) -> Optional[Glossary]:
    glossary_file = u.get("glossary_file")
    if not glossary_file:
        return None
    try:
        return load_glossary_csv(glossary_file)
    except FileNotFoundError:
        print(f"[config] ERROR: tenant '{name}' glossary_file '{glossary_file}' not found in glossary/", file=sys.stderr)
        sys.exit(1)


def _load_prompt(u: dict, name: str) -> str:
    prompt_file = u.get("system_prompt_file")
    if prompt_file:
        file_path = PROMPTS_DIR / prompt_file
        if not file_path.exists():
            print(f"[config] ERROR: tenant '{name}' system_prompt_file '{file_path}' not found", file=sys.stderr)
            sys.exit(1)
        return file_path.read_text(encoding="utf-8").strip()
    return u.get("system_prompt", "")


def load_config(path: str = "config.yaml") -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    upstreams: dict[str, UpstreamConfig] = {}
    for u in raw.get("upstreams", []):
        cfg = UpstreamConfig(
            id=u["id"],
            url=u["url"],
            api_key=u["api_key"],
            available_models=u.get("available_models", []),
        )
        upstreams[cfg.id] = cfg

    tenants: dict[str, TenantConfig] = {}
    for t in raw.get("tenants", []):
        upstream_id = t["upstream_id"]
        name = t.get("name", "?")

        if upstream_id not in upstreams:
            print(f"[config] ERROR: tenant '{name}' references unknown upstream_id '{upstream_id}'", file=sys.stderr)
            sys.exit(1)

        keys = t.get("keys", [])
        if not keys:
            print(f"[config] ERROR: tenant '{name}' has no keys defined", file=sys.stderr)
            sys.exit(1)

        system_prompt = _load_prompt(t, name)
        glossary = _load_glossary(t, name)
        tenant = TenantConfig(
            name=name,
            upstream_id=upstream_id,
            allowed_models=t.get("allowed_models", []),
            cors_origins=t.get("cors_origins", []),
            allowed_referers=t.get("allowed_referers", []),
            max_user_messages=t.get("max_user_messages"),
            max_chars=t.get("max_chars"),
            disable_thinking=t.get("disable_thinking"),
            system_prompt=system_prompt,
            glossary=glossary,
        )
        tenant.upstream = upstreams[upstream_id]

        # 校验 allowed_models 是 available_models 的子集
        invalid = set(tenant.allowed_models) - set(tenant.upstream.available_models)
        if invalid:
            print(
                f"[config] ERROR: tenant '{name}' allowed_models {invalid} "
                f"not in upstream '{upstream_id}' available_models",
                file=sys.stderr,
            )
            sys.exit(1)

        for key in keys:
            tenants[key] = tenant

    return AppConfig(upstreams=upstreams, tenants=tenants)
