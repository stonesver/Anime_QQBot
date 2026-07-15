import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from anime_qqbot.catalog.adapters.bangumi import BangumiClient
from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind

FIXTURES = Path(__file__).parents[1] / "fixtures" / "bangumi"


def fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
async def test_maps_search_and_sends_required_headers() -> None:
    route = respx.post("https://api.bgm.tv/v0/search/subjects").mock(
        return_value=httpx.Response(200, json=fixture("search.json"))
    )
    async with BangumiClient(
        "anime-qqbot/0.1 (contact@example.test)", access_token="token"
    ) as client:
        results = await client.search("夏日")

    assert results[0].title == "夏日物语"
    assert results[1].nsfw is True
    request = route.calls.last.request
    assert request.headers["user-agent"].startswith("anime-qqbot/0.1")
    assert request.headers["authorization"] == "Bearer token"
    assert json.loads(request.content)["filter"]["nsfw"] is False


@respx.mock
async def test_maps_detail_calendar_and_episode_date_fallback() -> None:
    respx.get("https://api.bgm.tv/v0/subjects/1001").mock(
        return_value=httpx.Response(200, json=fixture("subject.json"))
    )
    respx.get("https://api.bgm.tv/calendar").mock(
        return_value=httpx.Response(200, json=fixture("calendar.json"))
    )
    respx.get("https://api.bgm.tv/v0/episodes").mock(
        return_value=httpx.Response(200, json=fixture("episodes.json"))
    )
    async with BangumiClient("anime-qqbot/test") as client:
        detail = await client.get_detail(1001)
        calendar = await client.calendar()
        episodes = await client.episodes(1001)

    assert detail is not None and detail.score == 7.8 and detail.total_episodes == 12
    assert calendar[0].air_date == date(2026, 7, 3)
    assert len(episodes) == 1 and episodes[0].date_only


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, ProviderErrorKind.RATE_LIMITED),
        (503, ProviderErrorKind.TEMPORARY),
        (403, ProviderErrorKind.PERMANENT),
    ],
)
@respx.mock
async def test_classifies_http_errors(status: int, kind: ProviderErrorKind) -> None:
    respx.post("https://api.bgm.tv/v0/search/subjects").mock(return_value=httpx.Response(status))
    async with BangumiClient("anime-qqbot/test") as client:
        with pytest.raises(ProviderError) as caught:
            await client.search("test")
    assert caught.value.kind is kind


@respx.mock
async def test_invalid_json_is_an_internal_provider_error() -> None:
    respx.get("https://api.bgm.tv/calendar").mock(return_value=httpx.Response(200, text="not-json"))
    async with BangumiClient("anime-qqbot/test") as client:
        with pytest.raises(ProviderError) as caught:
            await client.calendar()
    assert caught.value.kind is ProviderErrorKind.INVALID_RESPONSE
