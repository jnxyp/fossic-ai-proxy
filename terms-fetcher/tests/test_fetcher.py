"""Tests for the ParaTranz API fetcher."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetcher import fetch_all_terms


def _make_response(results: list[dict], page: int = 1, page_count: int = 1):
    mock = MagicMock(spec=httpx.Response)
    mock.json.return_value = {"results": results, "page": page, "pageCount": page_count}
    mock.raise_for_status = MagicMock()
    return mock


@pytest.mark.asyncio
async def test_single_page():
    terms = [{"term": "flux", "translation": "幅能"}]
    resp = _make_response(terms, page=1, page_count=1)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_all_terms(3489, "key", "https://api.test")

    assert len(result) == 1
    assert result[0]["term"] == "flux"


@pytest.mark.asyncio
async def test_multiple_pages():
    page1 = _make_response([{"term": "flux", "translation": "幅能"}], page=1, page_count=2)
    page2 = _make_response([{"term": "shield", "translation": "护盾"}], page=2, page_count=2)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[page1, page2])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_all_terms(3489, "key", "https://api.test")

    assert len(result) == 2
    assert {t["term"] for t in result} == {"flux", "shield"}


@pytest.mark.asyncio
async def test_sends_auth_header():
    resp = _make_response([], page=1, page_count=1)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("fetcher.httpx.AsyncClient", return_value=mock_client):
        await fetch_all_terms(3489, "my-api-key", "https://api.test")

    call_kwargs = mock_client.get.call_args
    assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer my-api-key"


@pytest.mark.asyncio
async def test_empty_results():
    resp = _make_response([], page=1, page_count=1)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("fetcher.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_all_terms(3489, "key", "https://api.test")

    assert result == []
