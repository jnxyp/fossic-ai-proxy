"""Tests for proxy stream helpers."""
from __future__ import annotations

import asyncio
import json

from fastapi.responses import JSONResponse

from tests.conftest import make_agent, make_upstream
from proxy import _meta_text, _meta_sse_chunk, _json_to_sse_stream


def test_meta_text_contains_agent_model_upstream():
    up = make_upstream(id="qwen")
    ag = make_agent(up, id="starsector-qwen-mt-plus", model="qwen-mt-plus")
    meta = _meta_text(ag)
    assert "agent=starsector-qwen-mt-plus" in meta
    assert "model=qwen-mt-plus" in meta
    assert "upstream=qwen" in meta


def test_meta_text_ends_with_double_newline():
    up = make_upstream()
    ag = make_agent(up)
    assert _meta_text(ag).endswith("\n\n")


def test_meta_sse_chunk_is_valid_sse():
    up = make_upstream(id="qwen")
    ag = make_agent(up, id="starsector-agent", model="qwen-mt-flash")
    chunk = _meta_sse_chunk(ag)
    assert isinstance(chunk, bytes)
    text = chunk.decode()
    assert text.startswith("data: ")
    assert text.endswith("\n\n")


def test_meta_sse_chunk_contains_reasoning_content():
    up = make_upstream(id="qwen")
    ag = make_agent(up, id="agent-x", model="model-x")
    chunk = _meta_sse_chunk(ag)
    text = chunk.decode()
    line = next(l for l in text.split("\n") if l.startswith("data: "))
    data = json.loads(line[6:])
    rc = data["choices"][0]["delta"]["reasoning_content"]
    assert "agent=agent-x" in rc
    assert "model=model-x" in rc
    assert "upstream=qwen" in rc


# ── force_non_stream SSE wrapping ─────────────────────────────────────────────

def _make_json_resp(content: str, model: str = "qwen-mt-plus") -> JSONResponse:
    data = {
        "id": "chatcmpl-test",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
    return JSONResponse(content=data)


def _collect_stream(stream_resp) -> list[dict]:
    """Drain a StreamingResponse and return parsed SSE data objects."""
    async def _drain():
        chunks = []
        async for chunk in stream_resp.body_iterator:
            if isinstance(chunk, bytes):
                for line in chunk.decode().split("\n"):
                    line = line.strip()
                    if line.startswith("data: ") and not line.endswith("[DONE]"):
                        chunks.append(json.loads(line[6:]))
        return chunks
    return asyncio.get_event_loop().run_until_complete(_drain())


def test_json_to_sse_stream_emits_meta_first():
    up = make_upstream(id="qwen")
    ag = make_agent(up, id="plus-agent", model="qwen-mt-plus")
    resp = _json_to_sse_stream(_make_json_resp("翻译结果"), ag)
    chunks = _collect_stream(resp)
    assert "reasoning_content" in chunks[0]["choices"][0]["delta"]
    assert "agent=plus-agent" in chunks[0]["choices"][0]["delta"]["reasoning_content"]


def test_json_to_sse_stream_emits_content():
    up = make_upstream(id="qwen")
    ag = make_agent(up, id="plus-agent", model="qwen-mt-plus")
    resp = _json_to_sse_stream(_make_json_resp("翻译结果"), ag)
    chunks = _collect_stream(resp)
    content_chunks = [c for c in chunks if c["choices"][0]["delta"].get("content")]
    assert any("翻译结果" in c["choices"][0]["delta"]["content"] for c in content_chunks)


def test_json_to_sse_stream_ends_with_done():
    up = make_upstream(id="qwen")
    ag = make_agent(up, id="plus-agent", model="qwen-mt-plus")

    async def _check_done():
        raw = b""
        async for chunk in _json_to_sse_stream(_make_json_resp("x"), ag).body_iterator:
            if isinstance(chunk, bytes):
                raw += chunk
        return raw

    raw = asyncio.get_event_loop().run_until_complete(_check_done())
    assert b"data: [DONE]" in raw
