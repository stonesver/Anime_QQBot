"""Unit tests for AniList incremental sync (Task 13)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind
from anime_qqbot.catalog.models import AnimeDetail
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.catalog.sync_anilist import AniListSyncService
from anime_qqbot.clock import FrozenClock


class _StubAniList:
    def __init__(self, results: dict[int, AnimeDetail | None]) -> None:
        self._results = results
        self.calls: list[int] = []

    async def fetch_media(self, anilist_id: int) -> AnimeDetail | None:
        self.calls.append(anilist_id)
        return self._results.get(anilist_id)


def _engine():
    return create_async_engine(os.environ["TEST_DATABASE_URL"])


async def _reset(engine) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE source_snapshots, anime_source_links, "
            "anime_titles, airing_occurrences, external_entries, animes, "
            "source_sync_states RESTART IDENTITY CASCADE"
        )


@pytest.fixture
async def session_factory():
    engine = _engine()
    await _reset(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _detail(anilist_id: int) -> AnimeDetail:
    return AnimeDetail(
        subject_id=anilist_id,
        title_cn=f"Title {anilist_id}",
        title_jp=f"タイトル {anilist_id}",
        air_date=date(2026, 7, 1),
        summary="概要",
        score=8.0,
        total_episodes=12,
        nsfw=False,
    )


@pytest.mark.asyncio
async def test_sync_subject_creates_external_entry_and_snapshot(session_factory) -> None:
    stub = _StubAniList({21: _detail(21)})
    write = CatalogWriteRepository(session_factory)
    clock = FrozenClock(datetime(2026, 7, 27, tzinfo=UTC))
    sync = AniListSyncService(stub, write, clock)

    delta = await sync.sync_subject(21)

    assert stub.calls == [21]
    assert len(delta.added) == 1
    snap = await write.current_snapshot(delta.added[0].id)
    assert snap is not None
    assert snap.payload["title_romaji"] == "タイトル 21"


@pytest.mark.asyncio
async def test_sync_subject_skips_when_not_found(session_factory) -> None:
    stub = _StubAniList({22: None})
    write = CatalogWriteRepository(session_factory)
    clock = FrozenClock(datetime(2026, 7, 27, tzinfo=UTC))
    sync = AniListSyncService(stub, write, clock)

    delta = await sync.sync_subject(22)

    assert delta.added == ()


@pytest.mark.asyncio
async def test_sync_batch_stops_on_rate_limit(session_factory) -> None:
    class _RateLimited:
        async def fetch_media(self, anilist_id: int) -> AnimeDetail:
            raise ProviderError(
                ProviderErrorKind.RATE_LIMITED,
                "rate limited",
                retry_after=30,
            )

    sync = AniListSyncService(
        _RateLimited(),
        CatalogWriteRepository(session_factory),
        FrozenClock(datetime(2026, 7, 27, tzinfo=UTC)),
    )

    result = await sync.sync_batch([1, 2, 3])

    assert result.processed == 0
    assert result.failed == 1
    assert result.rate_limited is True


@pytest.mark.asyncio
async def test_sync_batch_processes_multiple_ids(session_factory) -> None:
    stub = _StubAniList({1: _detail(1), 2: _detail(2), 3: _detail(3)})
    sync = AniListSyncService(
        stub,
        CatalogWriteRepository(session_factory),
        FrozenClock(datetime(2026, 7, 27, tzinfo=UTC)),
    )

    result = await sync.sync_batch([1, 2, 3])

    assert result.processed == 3
    assert result.failed == 0
    assert result.rate_limited is False


@pytest.mark.asyncio
async def test_health_returns_healthy(session_factory) -> None:
    sync = AniListSyncService(
        _StubAniList({}),
        CatalogWriteRepository(session_factory),
        FrozenClock(datetime(2026, 7, 27, tzinfo=UTC)),
    )

    health = await sync.health()

    from anime_qqbot.catalog.ports import SourceHealthStatus

    assert health.status is SourceHealthStatus.HEALTHY
