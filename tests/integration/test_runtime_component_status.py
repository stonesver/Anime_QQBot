from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.operations.napcat_status import (
    NapCatProbeResult,
    NapCatStatus,
    NapCatStatusTracker,
)
from anime_qqbot.operations.runtime_status_repository import (
    RuntimeComponentStatusRepository,
)


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "TRUNCATE TABLE runtime_component_events, runtime_component_states CASCADE"
        )
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield sessions
    finally:
        await engine.dispose()


async def test_status_and_recent_transitions_survive_repository_rebuild(
    session_factory,
) -> None:
    repository = RuntimeComponentStatusRepository(session_factory)
    started_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    tracker = NapCatStatusTracker()
    online = tracker.observe(NapCatProbeResult.online(), observed_at=started_at)
    offline = tracker.observe(
        NapCatProbeResult.qq_offline(),
        observed_at=started_at + timedelta(minutes=1),
    )

    assert await repository.record("napcat", online) is True
    assert await repository.record("napcat", offline) is True

    loaded = await RuntimeComponentStatusRepository(session_factory).get("napcat")
    events = await repository.list_events("napcat")

    assert loaded == offline
    assert [event.status for event in events] == [
        NapCatStatus.QQ_OFFLINE,
        NapCatStatus.ONLINE,
    ]


async def test_only_twenty_most_recent_transitions_are_retained(session_factory) -> None:
    repository = RuntimeComponentStatusRepository(session_factory)
    started_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    tracker = NapCatStatusTracker()
    for index in range(25):
        result = NapCatProbeResult.online() if index % 2 == 0 else NapCatProbeResult.qq_offline()
        await repository.record(
            "napcat",
            tracker.observe(
                result,
                observed_at=started_at + timedelta(minutes=index),
            ),
        )

    events = await repository.list_events("napcat", limit=100)

    assert len(events) == 20
    assert events[0].occurred_at == datetime(2026, 7, 29, 12, 24, tzinfo=UTC)
