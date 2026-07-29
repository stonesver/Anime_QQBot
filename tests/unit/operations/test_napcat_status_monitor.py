import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from anime_qqbot.operations.napcat_status import (
    NapCatOneBotClient,
    NapCatProbeResult,
    NapCatStatus,
    NapCatStatusMonitor,
    NapCatStatusTracker,
)


def test_online_session_turns_red_immediately_when_qq_is_offline() -> None:
    started_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    tracker = NapCatStatusTracker()

    online = tracker.observe(NapCatProbeResult.online(), observed_at=started_at)
    offline = tracker.observe(
        NapCatProbeResult.qq_offline(),
        observed_at=started_at + timedelta(minutes=1),
    )

    assert online.status is NapCatStatus.ONLINE
    assert offline.status is NapCatStatus.QQ_OFFLINE
    assert offline.offline_since == datetime(2026, 7, 29, 12, 1, tzinfo=UTC)


def test_endpoint_only_turns_yellow_after_three_consecutive_failures() -> None:
    started_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    tracker = NapCatStatusTracker()
    tracker.observe(NapCatProbeResult.online(), observed_at=started_at)

    first = tracker.observe(
        NapCatProbeResult.failure(),
        observed_at=started_at + timedelta(minutes=1),
    )
    second = tracker.observe(
        NapCatProbeResult.failure(),
        observed_at=started_at + timedelta(minutes=2),
    )
    third = tracker.observe(
        NapCatProbeResult.failure(),
        observed_at=started_at + timedelta(minutes=3),
    )

    assert first.status is NapCatStatus.ONLINE
    assert second.status is NapCatStatus.ONLINE
    assert third.status is NapCatStatus.UNREACHABLE
    assert third.consecutive_failures == 3


def test_one_online_observation_recovers_and_clears_offline_time() -> None:
    started_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    tracker = NapCatStatusTracker()
    tracker.observe(NapCatProbeResult.qq_offline(), observed_at=started_at)

    recovered = tracker.observe(
        NapCatProbeResult.online(),
        observed_at=started_at + timedelta(minutes=1),
    )

    assert recovered.status is NapCatStatus.ONLINE
    assert recovered.consecutive_failures == 0
    assert recovered.offline_since is None


@pytest.mark.asyncio
async def test_onebot_probe_uses_token_and_reads_online_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        assert request.url.path == "/get_status"
        return httpx.Response(
            200,
            json={"status": "ok", "retcode": 0, "data": {"online": True, "good": True}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = NapCatOneBotClient(
            base_url="http://napcat:3000",
            token="secret-token",
            http=http,
        )

        result = await client.probe()

    assert result == NapCatProbeResult.online()


@pytest.mark.asyncio
async def test_onebot_probe_treats_invalid_response_as_failure() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"status": "ok", "data": {}})
        )
    ) as http:
        client = NapCatOneBotClient(
            base_url="http://napcat:3000",
            token="secret-token",
            http=http,
        )

        result = await client.probe()

    assert result == NapCatProbeResult.failure()


@pytest.mark.asyncio
async def test_onebot_probe_reports_qq_offline_when_endpoint_is_healthy() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "status": "ok",
                    "retcode": 0,
                    "data": {"online": False, "good": True},
                },
            )
        )
    ) as http:
        client = NapCatOneBotClient(
            base_url="http://napcat:3000",
            token="secret-token",
            http=http,
        )

        result = await client.probe()

    assert result == NapCatProbeResult.qq_offline()


@pytest.mark.asyncio
async def test_monitor_checks_immediately_and_stops_cleanly() -> None:
    recorded = asyncio.Event()
    snapshots = []

    class Client:
        async def probe(self):
            return NapCatProbeResult.online()

        async def close(self):
            return None

    class Repository:
        async def get(self, _component_name):
            return None

        async def record(self, component_name, snapshot):
            assert component_name == "napcat"
            snapshots.append(snapshot)
            recorded.set()
            return True

    monitor = NapCatStatusMonitor(
        client=Client(),
        repository=Repository(),
        interval_seconds=60,
    )

    task = asyncio.create_task(monitor.run())
    await asyncio.wait_for(recorded.wait(), timeout=1)
    await monitor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert [snapshot.status for snapshot in snapshots] == [NapCatStatus.ONLINE]
