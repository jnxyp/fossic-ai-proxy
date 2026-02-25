from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    project_id: int
    api_key: str
    base_url: str
    output_path: str
    interval_seconds: int


def load_config(path: str = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    p = raw.get("paratranz", {})
    return Config(
        project_id=int(p["project_id"]),
        api_key=p["api_key"],
        base_url=p.get("base_url", "https://paratranz.cn/api"),
        output_path=raw["output_path"],
        interval_seconds=int(raw.get("interval_seconds", 600)),
    )
