from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.catalog.adapters.animeschedule import AnimeScheduleTimetableEntry
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.catalog.sync_animeschedule import AnimeScheduleSyncService
from anime_qqbot.clock import FrozenClock
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)


class _TimetableClient:
    def __init__(self, entries: list[AnimeScheduleTimetableEntry]) -> None:
        self.entries = entries
        self.calls = 0

    async def raw_timetable(self) -> list[AnimeScheduleTimetableEntry]:
        self.calls += 1
        return self.entries


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "TRUNCATE TABLE source_snapshots, anime_source_links, airing_occurrences, "
            "external_entries, animes, source_sync_states RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def timetable(air_at: datetime) -> AnimeScheduleTimetableEntry:
    return AnimeScheduleTimetableEntry(
        route="thunder-3",
        title="Thunder 3",
        episode=6,
        air_at=air_at,
        air_type="raw",
        payload={
            "route": "thunder-3",
            "title": "Thunder 3",
            "episodeNumber": 6,
            "episodeDate": air_at.isoformat(),
            "airType": "raw",
        },
    )


async def test_timetable_updates_same_episode_without_duplicate(session_factory) -> None:
    now = datetime(2026, 8, 12, 8, tzinfo=UTC)
    anime_id = uuid4()
    entry_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Anime(
                    id=anime_id,
                    nsfw_flag="false",
                    disabled=False,
                    display_title="Thunder 3",
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=entry_id,
                    provider="animeschedule",
                    external_id="thunder-3",
                    url="https://animeschedule.net/anime/thunder-3",
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                AnimeSourceLink(
                    id=uuid4(),
                    anime_id=anime_id,
                    external_entry_id=entry_id,
                    status="confirmed",
                    evidence_type="cross_id",
                    confidence=0.98,
                    method="animeschedule_cross_id_v1",
                    created_at=now,
                ),
                SourceSnapshot(
                    id=uuid4(),
                    external_entry_id=entry_id,
                    version=1,
                    payload={"route": "thunder-3"},
                    source_time=now,
                    fetched_at=now,
                    expires_at=None,
                ),
            ]
        )

    client = _TimetableClient([timetable(datetime(2026, 8, 12, 14, 30, tzinfo=UTC))])
    service = AnimeScheduleSyncService(
        sessions=session_factory,
        client=client,  # type: ignore[arg-type]
        write_repo=CatalogWriteRepository(session_factory),
        clock=FrozenClock(now),
    )

    first = await service.sync_timetable()
    client.entries = [timetable(datetime(2026, 8, 12, 14, 45, tzinfo=UTC))]
    second = await service.sync_timetable()

    async with session_factory() as session:
        rows = (await session.execute(select(AiringOccurrenceRow))).scalars().all()
        snapshot_count = await session.scalar(select(func.count()).select_from(SourceSnapshot))
    assert client.calls == 2
    assert first.occurrences_written == 1
    assert second.occurrences_written == 1
    assert len(rows) == 1
    assert rows[0].air_at == datetime(2026, 8, 12, 14, 45, tzinfo=UTC)
    assert rows[0].source_event_key == "animeschedule:thunder-3:raw:06"
    assert snapshot_count == 3
