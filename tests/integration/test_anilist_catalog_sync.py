"""Unit tests for AniList incremental sync (Task 13)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind
from anime_qqbot.catalog.anilist_mapping import AniListLinkDiscoveryService
from anime_qqbot.catalog.models import AiringOccurrence, AnimeDetail, AnimeSummary
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.catalog.sync_anilist import AniListSyncService
from anime_qqbot.clock import FrozenClock
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)


class _StubAniList:
    def __init__(
        self,
        results: dict[int, AnimeDetail | None],
        schedules: dict[int, list[AiringOccurrence]] | None = None,
        searches: dict[str, list[AnimeSummary]] | None = None,
    ) -> None:
        self._results = results
        self._schedules = schedules or {}
        self._searches = searches or {}
        self.calls: list[int] = []

    async def fetch_media(self, anilist_id: int) -> AnimeDetail | None:
        self.calls.append(anilist_id)
        return self._results.get(anilist_id)

    async def airing_schedule(self, anilist_id: int) -> list[AiringOccurrence]:
        return self._schedules.get(anilist_id, [])

    async def search(self, query_text: str) -> list[AnimeSummary]:
        return self._searches.get(query_text, [])


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


@pytest.mark.asyncio
async def test_confirmed_link_persists_exact_airing_schedule(session_factory) -> None:
    now = datetime(2026, 7, 27, tzinfo=UTC)
    occurrence = AiringOccurrence(
        subject_id=21,
        air_date=date(2026, 8, 1),
        air_at=datetime(2026, 8, 1, 12, 30, tzinfo=UTC),
        episode=4,
        source="anilist",
        updated_at=now,
    )
    stub = _StubAniList({21: _detail(21)}, {21: [occurrence]})
    write = CatalogWriteRepository(session_factory)
    sync = AniListSyncService(stub, write, FrozenClock(now))
    delta = await sync.sync_subject(21)
    anime = await write.create_anime(display_title="Mapped")
    await write.add_source_link(
        anime_id=anime.id,
        external_entry_id=UUID(str(delta.added[0].id)),
        status="confirmed",
        evidence_type="manual",
        confidence=1.0,
        method="test",
    )

    await sync.sync_subject(21)

    async with session_factory() as session:
        row = (await session.execute(select(AiringOccurrenceRow))).scalar_one()
    assert row.anime_id == anime.id
    assert row.air_at == occurrence.air_at
    assert row.precision == "exact"


@pytest.mark.asyncio
async def test_discovery_confirms_unique_exact_native_title_and_air_date(
    session_factory,
) -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    anime_id = uuid4()
    bangumi_entry_id = uuid4()
    title = "対ありでした。 ～お嬢さまは格闘ゲームなんてしない～"
    candidate = AnimeSummary(
        subject_id=128757,
        title_cn=title,
        title_jp="Tai-Ari deshita.",
        air_date=date(2026, 7, 7),
        nsfw=False,
    )
    detail = _detail(128757)
    detail = AnimeDetail(
        subject_id=detail.subject_id,
        title_cn=detail.title_cn,
        title_jp=detail.title_jp,
        air_date=date(2026, 7, 7),
        summary=detail.summary,
        score=detail.score,
        total_episodes=detail.total_episodes,
        nsfw=detail.nsfw,
    )
    stub = _StubAniList(
        {128757: detail},
        searches={title: [candidate]},
    )
    async with session_factory() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                nsfw_flag="false",
                disabled=False,
                display_title="感谢对战。 ～大小姐才不玩格斗游戏～",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ExternalEntry(
                id=bangumi_entry_id,
                provider="bangumi",
                external_id="325767",
                url="https://bgm.tv/subject/325767",
                disabled=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AnimeSourceLink(
                id=uuid4(),
                anime_id=anime_id,
                external_entry_id=bangumi_entry_id,
                status="confirmed",
                evidence_type="manual",
                confidence=1.0,
                method="fixture",
                created_at=now,
            )
        )
        session.add(
            SourceSnapshot(
                id=uuid4(),
                external_entry_id=bangumi_entry_id,
                version=1,
                payload={
                    "title_jp": title,
                    "title_cn": "感谢对战。",
                    "air_date": "2026-07-07",
                    "total_episodes": 12,
                },
                source_time=now,
                fetched_at=now,
                expires_at=None,
            )
        )

    sync = AniListSyncService(
        stub,
        CatalogWriteRepository(session_factory),
        FrozenClock(now),
    )
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=stub,
        sync=sync,
        clock=FrozenClock(now),
    )

    result = await discovery.run_once(limit=10)

    assert result.links_confirmed == 1
    async with session_factory() as session:
        entry = (
            await session.execute(
                select(ExternalEntry).where(
                    ExternalEntry.provider == "anilist",
                    ExternalEntry.external_id == "128757",
                )
            )
        ).scalar_one()
        link = (
            await session.execute(
                select(AnimeSourceLink).where(AnimeSourceLink.external_entry_id == entry.id)
            )
        ).scalar_one()
    assert link.anime_id == anime_id
    assert link.status == "confirmed"
    assert link.evidence_type == "title_season_year"
