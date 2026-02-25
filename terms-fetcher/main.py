from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from config import load_config
from fetcher import fetch_all_terms
from logger import get_logger

log = get_logger()


def _to_output(terms: list[dict]) -> dict:
    return {
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "terms": [
            {
                "term": t["term"],
                "translation": t["translation"],
                "note": t.get("note") or "",
                "variants": t.get("variants") or [],
                "caseSensitive": t.get("caseSensitive", False),
            }
            for t in terms
            if (t.get("term") or "").strip() and (t.get("translation") or "").strip()
        ],
    }


async def fetch_and_write(cfg) -> None:
    log.info(f"fetching terms for project {cfg.project_id}")
    try:
        terms = await fetch_all_terms(cfg.project_id, cfg.api_key, cfg.base_url)
        data = _to_output(terms)

        out = Path(cfg.output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # atomic write: write to .tmp then rename
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(out)

        log.info(f"wrote {len(data['terms'])} terms to {cfg.output_path}")
    except Exception as e:
        log.error(f"fetch failed: {e}")


async def main() -> None:
    cfg = load_config()
    log.info(f"starting: project={cfg.project_id} interval={cfg.interval_seconds}s output={cfg.output_path}")
    while True:
        await fetch_and_write(cfg)
        await asyncio.sleep(cfg.interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
