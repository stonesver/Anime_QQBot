"""Contract tests for the AnimeSchedule v3 adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from anime_qqbot.catalog.adapters.animeschedule import (
    AnimeScheduleClient,
    AnimeScheduleConfig,
)
from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind

FIXTURES = Path(__file__).parents[1] / "fixtures" / "animeschedule"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
async def test_search_uses_bearer_token_and_maps_cross_ids() -> None:
    route = respx.get("https://animeschedule.net/api/v3/anime").mock(
        return_value=httpx.Response(200, json=fixture("search.json"))
    )
    async with AnimeScheduleClient(
        AnimeScheduleConfig(token=SecretStr("application-token"))
    ) as client:
        candidates = await client.search("Thunder 3")

    assert route.calls[0].request.headers["Authorization"] == "Bearer application-token"
    assert route.calls[0].request.url.params["q"] == "Thunder 3"
    assert candidates[0].route == "thunder-3"
    assert candidates[0].anilist_id == 207254
    assert "サンダー3" in candidates[0].aliases
    assert candidates[0].premiere is not None
    assert "application-token" not in repr(client)


@respx.mock
async def test_search_maps_nested_names_from_v3_response() -> None:
    respx.get("https://animeschedule.net/api/v3/anime").mock(
        return_value=httpx.Response(
            200,
            json={
                "page": 1,
                "totalAmount": 1,
                "anime": [
                    {
                        "route": "super-no-ura-de-yani-suu-futari",
                        "title": "Super no Ura de Yani Suu Futari",
                        "names": {
                            "romaji": "Super no Ura de Yani Suu Futari",
                            "english": "Smoking Behind the Supermarket with You",
                            "native": "スーパーの裏でヤニ吸うふたり",
                            "abbreviation": "Yanisuu",
                            "synonyms": ["Smoking Behind the Supermarket"],
                        },
                    }
                ],
            },
        )
    )
    async with AnimeScheduleClient(
        AnimeScheduleConfig(token=SecretStr("application-token"))
    ) as client:
        candidates = await client.search("スーパーの裏でヤニ吸うふたり")

    assert candidates[0].aliases == (
        "Super no Ura de Yani Suu Futari",
        "Smoking Behind the Supermarket with You",
        "スーパーの裏でヤニ吸うふたり",
        "Yanisuu",
        "Smoking Behind the Supermarket",
    )


@respx.mock
async def test_raw_timetable_requests_tokyo_timezone_and_maps_exact_airing() -> None:
    route = respx.get("https://animeschedule.net/api/v3/timetables/raw").mock(
        return_value=httpx.Response(200, json=fixture("timetable.json"))
    )
    async with AnimeScheduleClient(
        AnimeScheduleConfig(token=SecretStr("application-token"))
    ) as client:
        entries = await client.raw_timetable()

    assert route.calls[0].request.url.params["tz"] == "Asia/Tokyo"
    assert entries[0].route == "thunder-3"
    assert entries[0].episode == 6
    assert entries[0].air_at.tzinfo is not None
    assert entries[0].air_type == "raw"


@pytest.mark.parametrize(
    ("status", "kind"),
    [(429, ProviderErrorKind.RATE_LIMITED), (500, ProviderErrorKind.TEMPORARY)],
)
@respx.mock
async def test_http_failures_are_classified(status: int, kind: ProviderErrorKind) -> None:
    respx.get("https://animeschedule.net/api/v3/anime").mock(
        return_value=httpx.Response(status, headers={"Retry-After": "45"})
    )
    async with AnimeScheduleClient(
        AnimeScheduleConfig(token=SecretStr("application-token"))
    ) as client:
        with pytest.raises(ProviderError) as caught:
            await client.search("Thunder 3")

    assert caught.value.kind is kind
    if status == 429:
        assert caught.value.retry_after == 45


@respx.mock
async def test_invalid_json_is_invalid_response() -> None:
    respx.get("https://animeschedule.net/api/v3/anime").mock(
        return_value=httpx.Response(200, text="not-json")
    )
    async with AnimeScheduleClient(
        AnimeScheduleConfig(token=SecretStr("application-token"))
    ) as client:
        with pytest.raises(ProviderError) as caught:
            await client.search("Thunder 3")

    assert caught.value.kind is ProviderErrorKind.INVALID_RESPONSE
