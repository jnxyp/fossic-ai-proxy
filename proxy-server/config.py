from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml

from glossary import GlossaryLoader, make_glossary_loader
from logger import get_logger

log = get_logger()
PROMPTS_DIR = Path("prompts")


@dataclass
class UpstreamConfig:
    id: str
    url: str
    api_key: str
    available_models: list[str]


@dataclass
class AgentConfig:
    id: str
    upstream_id: str
    model: str
    system_prompt: str
    glossary: Optional[GlossaryLoader]
    enable_thinking: Optional[bool]
    extra_body: dict
    glossary_mode: Literal["system_message", "translation_options"] = "system_message"
    force_non_stream: bool = False
    system_prompt_position: Literal["system", "user_prefix"] = "system"
    upstream: UpstreamConfig = field(init=False)


@dataclass
class TenantConfig:
    name: str
    agent_id: str
    cors_origins: list[str] = field(default_factory=list)
    allowed_referers: list[str] = field(default_factory=list)
    max_user_messages: Optional[int] = None
    max_chars: Optional[int] = None
    upgrade_agent_id: Optional[str] = None
    upgrade_window: int = 600
    agent: AgentConfig = field(init=False)
    upgrade_agent: Optional[AgentConfig] = field(init=False, default=None)


@dataclass
class AppConfig:
    upstreams: dict[str, UpstreamConfig]
    agents: dict[str, AgentConfig]
    tenants: dict[str, TenantConfig]
    log_level: str = "info"


def _load_glossary(u: dict, name: str) -> Optional[GlossaryLoader]:
    glossary_file = u.get("glossary_file")
    if not glossary_file:
        return None
    loader = make_glossary_loader(glossary_file)
    log.info(f"agent '{name}' glossary registered: {glossary_file} (loaded on first use)")
    return loader


def _load_prompt(u: dict, name: str) -> str:
    prompt_file = u.get("system_prompt_file")
    if prompt_file:
        file_path = PROMPTS_DIR / prompt_file
        if not file_path.exists():
            log.error(f"agent '{name}' system_prompt_file '{file_path}' not found")
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

    agents: dict[str, AgentConfig] = {}
    for a in raw.get("agents", []):
        agent_id = a["id"]
        upstream_id = a["upstream_id"]

        if upstream_id not in upstreams:
            log.error(f"agent '{agent_id}' references unknown upstream_id '{upstream_id}'")
            sys.exit(1)

        system_prompt = _load_prompt(a, agent_id)
        glossary = _load_glossary(a, agent_id)

        agent = AgentConfig(
            id=agent_id,
            upstream_id=upstream_id,
            model=a["model"],
            system_prompt=system_prompt,
            glossary=glossary,
            enable_thinking=a.get("enable_thinking"),
            extra_body=a.get("extra_body") or {},
            glossary_mode=a.get("glossary_mode", "system_message"),
            force_non_stream=bool(a.get("force_non_stream", False)),
            system_prompt_position=a.get("system_prompt_position", "system"),
        )
        agent.upstream = upstreams[upstream_id]
        agents[agent_id] = agent

    tenants: dict[str, TenantConfig] = {}
    for t in raw.get("tenants", []):
        agent_id = t["agent_id"]
        name = t.get("name", "?")

        if agent_id not in agents:
            log.error(f"tenant '{name}' references unknown agent_id '{agent_id}'")
            sys.exit(1)

        keys = t.get("keys", [])
        if not keys:
            log.error(f"tenant '{name}' has no keys defined")
            sys.exit(1)

        upgrade_agent_id = t.get("upgrade_agent_id")
        if upgrade_agent_id and upgrade_agent_id not in agents:
            log.error(f"tenant '{name}' references unknown upgrade_agent_id '{upgrade_agent_id}'")
            sys.exit(1)

        tenant = TenantConfig(
            name=name,
            agent_id=agent_id,
            cors_origins=t.get("cors_origins", []),
            allowed_referers=t.get("allowed_referers", []),
            max_user_messages=t.get("max_user_messages"),
            max_chars=t.get("max_chars"),
            upgrade_agent_id=upgrade_agent_id,
            upgrade_window=t.get("upgrade_window", 15),
        )
        tenant.agent = agents[agent_id]
        if upgrade_agent_id:
            tenant.upgrade_agent = agents[upgrade_agent_id]

        for key in keys:
            tenants[key] = tenant

    log.info(f"loaded {len(tenants)} tenant(s), {len(agents)} agent(s), "
             f"{len(upstreams)} upstream(s), log_level={raw.get('log_level', 'info').upper()}")
    return AppConfig(
        upstreams=upstreams,
        agents=agents,
        tenants=tenants,
        log_level=raw.get("log_level", "info"),
    )
