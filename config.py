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
class UserConfig:
    key: str
    name: str
    upstream_id: str
    allowed_models: list[str]
    system_prompt: str
    cors_origins: list[str] = field(default_factory=list)
    allowed_referers: list[str] = field(default_factory=list)
    disable_thinking: bool = False
    glossary: Optional[Glossary] = None
    upstream: UpstreamConfig = field(init=False)


@dataclass
class AppConfig:
    upstreams: dict[str, UpstreamConfig]
    users: dict[str, UserConfig]


def _load_glossary(u: dict, name: str) -> Optional[Glossary]:
    glossary_file = u.get("glossary_file")
    if not glossary_file:
        return None
    try:
        return load_glossary_csv(glossary_file)
    except FileNotFoundError:
        print(f"[config] ERROR: user '{name}' glossary_file '{glossary_file}' not found in glossary/", file=sys.stderr)
        sys.exit(1)


def _load_prompt(u: dict, name: str) -> str:
    prompt_file = u.get("system_prompt_file")
    if prompt_file:
        file_path = PROMPTS_DIR / prompt_file
        if not file_path.exists():
            print(f"[config] ERROR: user '{name}' system_prompt_file '{file_path}' not found", file=sys.stderr)
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

    users: dict[str, UserConfig] = {}
    for u in raw.get("users", []):
        upstream_id = u["upstream_id"]
        if upstream_id not in upstreams:
            print(f"[config] ERROR: user '{u['name']}' references unknown upstream_id '{upstream_id}'", file=sys.stderr)
            sys.exit(1)

        system_prompt = _load_prompt(u, u.get("name", "?"))
        glossary = _load_glossary(u, u.get("name", "?"))
        user = UserConfig(
            key=u["key"],
            name=u["name"],
            upstream_id=upstream_id,
            allowed_models=u.get("allowed_models", []),
            cors_origins=u.get("cors_origins", []),
            allowed_referers=u.get("allowed_referers", []),
            disable_thinking=u.get("disable_thinking", False),
            system_prompt=system_prompt,
            glossary=glossary,
        )
        user.upstream = upstreams[upstream_id]

        # 校验 allowed_models 是 available_models 的子集
        invalid = set(user.allowed_models) - set(user.upstream.available_models)
        if invalid:
            print(
                f"[config] ERROR: user '{user.name}' allowed_models {invalid} "
                f"not in upstream '{upstream_id}' available_models",
                file=sys.stderr,
            )
            sys.exit(1)

        users[user.key] = user

    return AppConfig(upstreams=upstreams, users=users)
