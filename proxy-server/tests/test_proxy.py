"""Tests for proxy stream helpers."""
from __future__ import annotations

import json

from tests.conftest import make_agent, make_upstream
from proxy import _meta_text, _meta_sse_chunk


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
