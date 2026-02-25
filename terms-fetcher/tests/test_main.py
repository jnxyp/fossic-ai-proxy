"""Tests for terms-fetcher main logic."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add parent dir so imports work without install
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import _to_output, fetch_and_write
from config import Config


# ── _to_output ────────────────────────────────────────────────────────────────

def test_to_output_basic():
    terms = [{"term": "flux", "translation": "幅能", "note": "energy", "variants": [], "caseSensitive": False}]
    result = _to_output(terms)
    assert "updatedAt" in result
    assert len(result["terms"]) == 1
    assert result["terms"][0]["term"] == "flux"
    assert result["terms"][0]["translation"] == "幅能"


def test_to_output_skips_empty_term():
    terms = [
        {"term": "", "translation": "幅能", "note": ""},
        {"term": "  ", "translation": "幅能", "note": ""},
        {"term": "flux", "translation": "幅能", "note": ""},
    ]
    result = _to_output(terms)
    assert len(result["terms"]) == 1


def test_to_output_skips_empty_translation():
    terms = [
        {"term": "flux", "translation": "", "note": ""},
        {"term": "shield", "translation": "护盾", "note": ""},
    ]
    result = _to_output(terms)
    assert len(result["terms"]) == 1
    assert result["terms"][0]["term"] == "shield"


def test_to_output_fills_defaults():
    terms = [{"term": "flux", "translation": "幅能"}]
    result = _to_output(terms)
    item = result["terms"][0]
    assert item["note"] == ""
    assert item["variants"] == []
    assert item["caseSensitive"] is False


def test_to_output_preserves_variants():
    terms = [{"term": "Domain", "translation": "领域", "variants": ["The Domain"]}]
    result = _to_output(terms)
    assert result["terms"][0]["variants"] == ["The Domain"]


def test_to_output_empty_input():
    result = _to_output([])
    assert result["terms"] == []
    assert "updatedAt" in result


# ── fetch_and_write ───────────────────────────────────────────────────────────

@pytest.fixture
def cfg(tmp_path):
    return Config(
        project_id=3489,
        api_key="test-key",
        base_url="https://paratranz.cn/api",
        output_path=str(tmp_path / "terms.json"),
        interval_seconds=3600,
    )


@pytest.mark.asyncio
async def test_fetch_and_write_creates_file(cfg, tmp_path):
    mock_terms = [{"term": "flux", "translation": "幅能"}]
    with patch("main.fetch_all_terms", new=AsyncMock(return_value=mock_terms)):
        await fetch_and_write(cfg)
    out = Path(cfg.output_path)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["terms"]) == 1
    assert data["terms"][0]["term"] == "flux"


@pytest.mark.asyncio
async def test_fetch_and_write_no_tmp_file_left(cfg, tmp_path):
    mock_terms = [{"term": "flux", "translation": "幅能"}]
    with patch("main.fetch_all_terms", new=AsyncMock(return_value=mock_terms)):
        await fetch_and_write(cfg)
    tmp = Path(cfg.output_path).with_suffix(".tmp")
    assert not tmp.exists()


@pytest.mark.asyncio
async def test_fetch_and_write_handles_error_gracefully(cfg):
    with patch("main.fetch_all_terms", new=AsyncMock(side_effect=Exception("network error"))):
        # Should not raise
        await fetch_and_write(cfg)
    assert not Path(cfg.output_path).exists()
