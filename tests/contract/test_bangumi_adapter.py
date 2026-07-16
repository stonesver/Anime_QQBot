import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from anime_qqbot.catalog.adapters.bangumi import BangumiClient
from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind
from anime_qqbot.clock import FrozenClock

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


async def test_injected_client_still_uses_absolute_bangumi_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.bgm.tv/calendar"
        return httpx.Response(200, json=fixture("calendar.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as shared_client:
        client = BangumiClient("anime-qqbot/test", client=shared_client)
        calendar = await client.calendar()

    assert calendar[0].subject_id == 1001


async def test_connection_failure_falls_back_to_next_configured_endpoint() -> None:
    requested_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host == "api.bgm.tv":
            raise httpx.ConnectError("connection failed", request=request)
        return httpx.Response(200, json=fixture("calendar.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as shared_client:
        client = BangumiClient(
            "anime-qqbot/test",
            fallback_urls=("https://mirror.example",),
            client=shared_client,
        )
        calendar = await client.calendar()

    assert calendar[0].subject_id == 1001
    assert requested_urls == [
        "https://api.bgm.tv/calendar",
        "https://mirror.example/calendar",
    ]


async def test_timeout_falls_back_to_next_configured_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.bgm.tv":
            raise httpx.ReadTimeout("request timed out", request=request)
        return httpx.Response(200, json=fixture("calendar.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as shared_client:
        client = BangumiClient(
            "anime-qqbot/test",
            fallback_urls=("https://mirror.example",),
            client=shared_client,
        )
        calendar = await client.calendar()

    assert calendar[0].subject_id == 1001


@pytest.mark.parametrize("status", [429, 503])
@respx.mock
async def test_temporary_http_failure_falls_back_to_next_endpoint(status: int) -> None:
    primary = respx.get("https://api.bgm.tv/calendar").mock(return_value=httpx.Response(status))
    fallback = respx.get("https://mirror.example/calendar").mock(
        return_value=httpx.Response(200, json=fixture("calendar.json"))
    )

    async with BangumiClient(
        "anime-qqbot/test", fallback_urls=("https://mirror.example",)
    ) as client:
        calendar = await client.calendar()

    assert calendar[0].subject_id == 1001
    assert primary.called
    assert fallback.called


@respx.mock
async def test_invalid_json_falls_back_to_next_endpoint() -> None:
    respx.get("https://api.bgm.tv/calendar").mock(return_value=httpx.Response(200, text="not-json"))
    fallback = respx.get("https://mirror.example/calendar").mock(
        return_value=httpx.Response(200, json=fixture("calendar.json"))
    )

    async with BangumiClient(
        "anime-qqbot/test", fallback_urls=("https://mirror.example",)
    ) as client:
        calendar = await client.calendar()

    assert calendar[0].subject_id == 1001
    assert fallback.called


@respx.mock
async def test_permanent_http_failure_does_not_use_fallback_endpoint() -> None:
    respx.get("https://api.bgm.tv/calendar").mock(return_value=httpx.Response(403))
    fallback = respx.get("https://mirror.example/calendar").mock(
        return_value=httpx.Response(200, json=fixture("calendar.json"))
    )

    async with BangumiClient(
        "anime-qqbot/test", fallback_urls=("https://mirror.example",)
    ) as client:
        with pytest.raises(ProviderError) as caught:
            await client.calendar()

    assert caught.value.kind is ProviderErrorKind.PERMANENT
    assert not fallback.called


async def test_access_token_is_not_forwarded_to_fallback_endpoint() -> None:
    authorization_by_host: dict[str, str | None] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host is not None
        authorization_by_host[request.url.host] = request.headers.get("authorization")
        if request.url.host == "api.bgm.tv":
            return httpx.Response(503)
        return httpx.Response(200, json=fixture("calendar.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as shared_client:
        client = BangumiClient(
            "anime-qqbot/test",
            access_token="secret-token",
            fallback_urls=("https://mirror.example",),
            client=shared_client,
        )
        await client.calendar()

    assert authorization_by_host == {
        "api.bgm.tv": "Bearer secret-token",
        "mirror.example": None,
    }


async def test_failed_endpoint_is_skipped_until_cooldown_expires() -> None:
    clock = FrozenClock(datetime(2026, 7, 16, tzinfo=UTC))
    requested_hosts: list[str] = []
    primary_attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal primary_attempts
        assert request.url.host is not None
        requested_hosts.append(request.url.host)
        if request.url.host == "api.bgm.tv":
            primary_attempts += 1
            if primary_attempts == 1:
                return httpx.Response(503)
        return httpx.Response(200, json=fixture("calendar.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as shared_client:
        client = BangumiClient(
            "anime-qqbot/test",
            fallback_urls=("https://mirror.example",),
            clock=clock,
            client=shared_client,
        )
        await client.calendar()
        await client.calendar()
        clock.advance(timedelta(minutes=5))
        await client.calendar()

    assert requested_hosts == [
        "api.bgm.tv",
        "mirror.example",
        "mirror.example",
        "api.bgm.tv",
    ]


async def test_client_probes_earliest_endpoint_when_all_are_cooling_down() -> None:
    clock = FrozenClock(datetime(2026, 7, 16, tzinfo=UTC))
    requested_hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host is not None
        requested_hosts.append(request.url.host)
        if len(requested_hosts) <= 2:
            return httpx.Response(503)
        return httpx.Response(200, json=fixture("calendar.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as shared_client:
        client = BangumiClient(
            "anime-qqbot/test",
            fallback_urls=("https://mirror.example",),
            clock=clock,
            client=shared_client,
        )
        with pytest.raises(ProviderError):
            await client.calendar()
        calendar = await client.calendar()

    assert calendar[0].subject_id == 1001
    assert requested_hosts == ["api.bgm.tv", "mirror.example", "api.bgm.tv"]


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
