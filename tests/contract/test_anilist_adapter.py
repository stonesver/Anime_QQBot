"""Contract tests for the AniList adapter (Task 12)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx

from anime_qqbot.catalog.adapters.anilist import AniListClient
from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind

FIXTURES = Path(__file__).parents[1] / "fixtures" / "anilist"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
async def test_fetch_media_maps_to_anime_detail() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, json=fixture("media.json"))
    )
    async with AniListClient() as client:
        detail = await client.fetch_media(21)

    assert detail is not None
    assert detail.subject_id == 21
    assert detail.title_jp == "Natsu Monogatari"
    assert detail.title_cn == "夏物語"
    assert detail.total_episodes == 12
    assert detail.score == 78.0
    assert detail.nsfw is False


@respx.mock
async def test_search_returns_mapped_summaries() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, json=fixture("search.json"))
    )
    async with AniListClient() as client:
        results = await client.search("Natsu")

    assert results[0].subject_id == 21
    assert results[0].title_jp == "Natsu Monogatari"


@respx.mock
async def test_airing_schedule_parses_known_episodes() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, json=fixture("airing_schedule.json"))
    )
    async with AniListClient() as client:
        episodes = await client.airing_schedule(21)

    assert len(episodes) == 2
    assert episodes[0].episode == 1
    assert episodes[0].source == "anilist"
    assert episodes[0].air_at is not None
    assert episodes[0].date_only is False


@respx.mock
async def test_429_classifies_as_rate_limited() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(
            429,
            json=fixture("rate_limited.json"),
            headers={"Retry-After": "30"},
        )
    )
    async with AniListClient() as client:
        with pytest.raises(ProviderError) as caught:
            await client.fetch_media(21)

    assert caught.value.kind is ProviderErrorKind.RATE_LIMITED
    assert caught.value.retry_after == 30


@respx.mock
async def test_server_error_classifies_as_temporary() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(503, json={"data": None})
    )
    async with AniListClient() as client:
        with pytest.raises(ProviderError) as caught:
            await client.fetch_media(21)

    assert caught.value.kind is ProviderErrorKind.TEMPORARY


@respx.mock
async def test_graphql_errors_classify_as_invalid() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, json=fixture("rate_limited.json"))
    )
    async with AniListClient() as client:
        with pytest.raises(ProviderError) as caught:
            await client.fetch_media(21)

    assert caught.value.kind is ProviderErrorKind.INVALID_RESPONSE


@respx.mock
async def test_invalid_json_classifies_as_invalid() -> None:
    respx.post("https://graphql.anilist.co").mock(
        return_value=httpx.Response(200, text="not json")
    )
    async with AniListClient() as client:
        with pytest.raises(ProviderError) as caught:
            await client.fetch_media(21)

    assert caught.value.kind is ProviderErrorKind.INVALID_RESPONSE


def test_adapter_does_not_leak_httpx_response() -> None:
    import inspect

    fetch_sig = inspect.signature(AniListClient.fetch_media)
    schedule_sig = inspect.signature(AniListClient.airing_schedule)
    search_sig = inspect.signature(AniListClient.search)

    assert "httpx.Response" not in str(fetch_sig.return_annotation)
    assert "httpx.Response" not in str(schedule_sig.return_annotation)
    assert "httpx.Response" not in str(search_sig.return_annotation)
    # uuid4 imported is fine; no real leak
    _ = uuid4()