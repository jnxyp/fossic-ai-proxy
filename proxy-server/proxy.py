from __future__ import annotations

import json

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from config import TenantConfig

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)
REJECT_MARKER = "PROXY_REJECT:"


def _parse_sse_content(chunk: bytes) -> str:
    """Extract delta content text from SSE chunk(s)."""
    text = ""
    for line in chunk.decode(errors="replace").split("\n"):
        line = line.strip()
        if line.startswith("data: ") and not line.endswith("[DONE]"):
            try:
                data = json.loads(line[6:])
                content = (data.get("choices", [{}])[0]
                           .get("delta", {})
                           .get("content") or "")
                text += content
            except Exception:
                pass
    return text


async def forward(body: dict, tenant: TenantConfig) -> StreamingResponse | JSONResponse:
    upstream = tenant.agent.upstream
    headers = {
        "Authorization": f"Bearer {upstream.api_key}",
        "Content-Type": "application/json",
    }

    is_stream = body.get("stream", False)

    if is_stream:
        return await _stream_response(upstream.url, headers, body)
    else:
        return await _non_stream(upstream.url, headers, body)


async def _non_stream(url: str, headers: dict, body: dict) -> JSONResponse:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=body)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    content = (data.get("choices", [{}])[0]
               .get("message", {})
               .get("content", "") or "")

    if isinstance(content, str) and content.startswith(REJECT_MARKER):
        reason_str = content[len(REJECT_MARKER):]
        try:
            reason = json.loads(reason_str).get("reason", "请求被拒绝")
        except Exception:
            reason = "请求被拒绝"
        raise HTTPException(status_code=403, detail=reason)

    return JSONResponse(content=data, status_code=200)


async def _stream_response(url: str, headers: dict, body: dict) -> StreamingResponse | JSONResponse:
    """
    Start the streaming request, buffer the beginning to detect PROXY_REJECT,
    then either raise HTTPException or return a StreamingResponse.
    """
    client = httpx.AsyncClient(timeout=TIMEOUT)
    req = client.build_request("POST", url, headers=headers, json=body)
    resp = await client.send(req, stream=True)

    if resp.status_code != 200:
        error_body = await resp.aread()
        await resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=resp.status_code, detail=error_body.decode())

    # Reuse the same iterator across buffering and streaming phases
    raw_iter = resp.aiter_raw()
    buffered_chunks: list[bytes] = []
    content_so_far = ""

    async for chunk in raw_iter:
        if not chunk:
            continue
        buffered_chunks.append(chunk)
        content_so_far += _parse_sse_content(chunk)
        if len(content_so_far) >= len(REJECT_MARKER):
            break

    # Check for rejection
    if content_so_far.startswith(REJECT_MARKER):
        async for chunk in raw_iter:
            if chunk:
                content_so_far += _parse_sse_content(chunk)
        await resp.aclose()
        await client.aclose()

        reason_str = content_so_far[len(REJECT_MARKER):]
        try:
            reason = json.loads(reason_str).get("reason", "请求被拒绝")
        except Exception:
            reason = "请求被拒绝"
        raise HTTPException(status_code=403, detail=reason)

    # Not a rejection — yield buffered chunks then continue from the same iterator
    async def gen():
        try:
            for chunk in buffered_chunks:
                yield chunk
            async for chunk in raw_iter:
                if chunk:
                    yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream")
