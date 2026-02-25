from __future__ import annotations

import json

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from config import AgentConfig, TenantConfig

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)
REJECT_MARKER = "PROXY_REJECT:"


def _meta_text(agent: AgentConfig) -> str:
    return f"本次请求由代理「{agent.id}」处理，使用模型 {agent.model}，上游服务 {agent.upstream.id}。\n\n"


def _meta_sse_chunk(agent: AgentConfig) -> bytes:
    data = {
        "id": "proxy-meta",
        "choices": [{"index": 0, "delta": {"reasoning_content": _meta_text(agent)}, "finish_reason": None}],
    }
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


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


def _json_to_sse_stream(json_resp: JSONResponse, agent: AgentConfig) -> StreamingResponse:
    """Wrap a non-streaming JSON response as an SSE stream, prefixed with the meta chunk."""
    data = json.loads(json_resp.body)
    message = data.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "") or ""
    chunk = {
        "id": data.get("id", "chatcmpl-proxy"),
        "object": "chat.completion.chunk",
        "model": data.get("model", ""),
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": "stop"}],
    }

    async def gen():
        yield _meta_sse_chunk(agent)
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def forward(body: dict, tenant: TenantConfig, agent: AgentConfig | None = None) -> StreamingResponse | JSONResponse:
    effective = agent or tenant.agent
    upstream = effective.upstream
    headers = {
        "Authorization": f"Bearer {upstream.api_key}",
        "Content-Type": "application/json",
    }

    is_stream = body.get("stream", False)

    if is_stream and effective.force_non_stream:
        # Agent doesn't support streaming: fetch non-stream, wrap as SSE
        non_stream_body = {k: v for k, v in body.items() if k != "stream"}
        json_resp = await _non_stream(upstream.url, headers, non_stream_body)
        return _json_to_sse_stream(json_resp, effective)
    elif is_stream:
        return await _stream_response(upstream.url, headers, body, effective)
    else:
        return await _non_stream(upstream.url, headers, body, effective)


async def _non_stream(url: str, headers: dict, body: dict, agent: AgentConfig | None = None) -> JSONResponse:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=body)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    message = data.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "") or ""

    if isinstance(content, str) and content.startswith(REJECT_MARKER):
        reason_str = content[len(REJECT_MARKER):]
        try:
            reason = json.loads(reason_str).get("reason", "请求被拒绝")
        except Exception:
            reason = "请求被拒绝"
        raise HTTPException(status_code=403, detail=reason)

    if agent is not None:
        meta = _meta_text(agent)
        existing_rc = message.get("reasoning_content") or ""
        message["reasoning_content"] = meta + existing_rc
        data["choices"][0]["message"] = message

    return JSONResponse(content=data, status_code=200)


async def _stream_response(url: str, headers: dict, body: dict, agent: AgentConfig) -> StreamingResponse | JSONResponse:
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

    # Not a rejection — yield meta chunk first, then buffered chunks, then the rest
    async def gen():
        try:
            yield _meta_sse_chunk(agent)
            for chunk in buffered_chunks:
                yield chunk
            async for chunk in raw_iter:
                if chunk:
                    yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream")
