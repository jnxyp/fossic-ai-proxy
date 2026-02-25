from __future__ import annotations

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from config import UserConfig

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)


async def forward(body: dict, user: UserConfig) -> StreamingResponse | JSONResponse:
    upstream = user.upstream
    headers = {
        "Authorization": f"Bearer {upstream.api_key}",
        "Content-Type": "application/json",
    }

    is_stream = body.get("stream", False)

    if is_stream:
        return StreamingResponse(
            _stream(upstream.url, headers, body),
            media_type="text/event-stream",
        )
    else:
        return await _non_stream(upstream.url, headers, body)


async def _non_stream(url: str, headers: dict, body: dict) -> JSONResponse:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=body)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return JSONResponse(content=resp.json(), status_code=200)


async def _stream(url: str, headers: dict, body: dict):
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                error_body = await resp.aread()
                raise HTTPException(status_code=resp.status_code, detail=error_body.decode())
            async for chunk in resp.aiter_raw():
                if chunk:
                    yield chunk
