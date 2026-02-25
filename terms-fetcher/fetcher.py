from __future__ import annotations

import httpx

PAGE_SIZE = 800  # ParaTranz max


async def fetch_all_terms(project_id: int, api_key: str, base_url: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {api_key}"}
    terms: list[dict] = []
    page = 1

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            resp = await client.get(
                f"{base_url}/projects/{project_id}/terms",
                headers=headers,
                params={"page": page, "pageSize": PAGE_SIZE},
            )
            resp.raise_for_status()
            data = resp.json()
            terms.extend(data.get("results", []))
            if page >= data.get("pageCount", 1):
                break
            page += 1

    return terms
