from __future__ import annotations

import os
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.catalog.bangumi_sync import BangumiCatalogSync
from anime_qqbot.catalog.enrichment import CatalogEnrichmentRunner
from anime_qqbot.catalog.models import AnimeDetail, AnimeSummary
from anime_qqbot.catalog.repository_v2 import CatalogReadRepository, CatalogWriteRepository
from anime_qqbot.clock import FrozenClock


class _Bangumi:
    async def search(self, query: str) -> list[AnimeSummary]:
        assert query == "夏日物语"
        return [
            AnimeSummary(
                subject_id=4242,
                title_cn="夏日物语",
                title_jp="夏の日物語",
                air_date=date(2026, 7, 7),
                nsfw=False,
            )
        ]

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        assert subject_id == 4242
        return AnimeDetail(
            subject_id=4242,
            title_cn="夏日物语",
            title_jp="夏の日物語",
            air_date=date(2026, 7, 7),
            summary="简介",
            nsfw=False,
        )

    async def episodes(self, subject_id: int) -> list[object]:
        assert subject_id == 4242
        return []


class _AniListDiscovery:
    def __init__(self, result: bool = False) -> None:
        self.calls: list[UUID] = []
        self.result = result

    async def enrich_anime(self, anime_id: UUID) -> bool:
        self.calls.append(anime_id)
        return self.result


class _FailingAniListDiscovery(_AniListDiscovery):
    async def enrich_anime(self, anime_id: UUID) -> bool:
        self.calls.append(anime_id)
        raise RuntimeError("AniList unavailable")


@pytest.fixture
async def sessions() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE source_snapshots, anime_source_links, "
            "anime_titles, airing_occurrences, external_entries, animes, "
            "source_sync_states RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_request_populates_local_catalogue(sessions) -> None:
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)
    bangumi = _Bangumi()
    anilist = _AniListDiscovery()
    runner = CatalogEnrichmentRunner(
        bangumi=bangumi,
        bangumi_sync=BangumiCatalogSync(
            bangumi,
            CatalogWriteRepository(sessions),
            clock=FrozenClock(now),
        ),
        anilist=anilist,
        mikan=lambda _anime_id, _now: _unused_mikan(),
        clock=FrozenClock(now),
        sessions=sessions,
    )

    summary = await runner.run({"trigger": "search_miss", "query": "夏日物语"})

    rows = await CatalogReadRepository(sessions).search_anime_by_title("夏日物语")
    assert summary == {
        "trigger": "search_miss",
        "bangumi_synced": 1,
        "anilist_links": 0,
    }
    assert len(rows) == 1
    assert rows[0].display_title == "夏日物语"
    assert anilist.calls == [rows[0].id]


async def _unused_mikan() -> int:
    raise AssertionError("Mikan must not run for a search-only request")


@pytest.mark.asyncio
async def test_subscription_request_enriches_exact_anime_immediately(sessions) -> None:
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)
    bangumi = _Bangumi()
    bangumi_sync = BangumiCatalogSync(
        bangumi,
        CatalogWriteRepository(sessions),
        clock=FrozenClock(now),
    )
    seeded = await bangumi_sync.sync_subject(4242)
    anilist = _AniListDiscovery(result=True)
    mikan_calls: list[tuple[UUID, datetime]] = []

    async def _mikan(anime_id: UUID, requested_at: datetime) -> int:
        mikan_calls.append((anime_id, requested_at))
        return 1

    runner = CatalogEnrichmentRunner(
        bangumi=bangumi,
        bangumi_sync=bangumi_sync,
        anilist=anilist,
        mikan=_mikan,
        clock=FrozenClock(now),
        sessions=sessions,
    )

    summary = await runner.run(
        {
            "trigger": "subscription",
            "anime_id": str(seeded.source_link.anime_id),
        }
    )

    assert summary == {
        "trigger": "subscription",
        "bangumi_synced": 1,
        "anilist_links": 1,
        "mikan_links": 1,
    }
    assert anilist.calls == [seeded.source_link.anime_id]
    assert mikan_calls == [(seeded.source_link.anime_id, now)]


@pytest.mark.asyncio
async def test_subscription_attempts_mikan_when_anilist_fails(sessions) -> None:
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)
    bangumi = _Bangumi()
    bangumi_sync = BangumiCatalogSync(
        bangumi,
        CatalogWriteRepository(sessions),
        clock=FrozenClock(now),
    )
    seeded = await bangumi_sync.sync_subject(4242)
    anilist = _FailingAniListDiscovery()
    mikan_calls: list[UUID] = []

    async def _mikan(anime_id: UUID, _requested_at: datetime) -> int:
        mikan_calls.append(anime_id)
        return 1

    runner = CatalogEnrichmentRunner(
        bangumi=bangumi,
        bangumi_sync=bangumi_sync,
        anilist=anilist,
        mikan=_mikan,
        clock=FrozenClock(now),
        sessions=sessions,
    )

    with pytest.raises(RuntimeError, match="anilist"):
        await runner.run(
            {
                "trigger": "subscription",
                "anime_id": str(seeded.source_link.anime_id),
            }
        )

    assert mikan_calls == [seeded.source_link.anime_id]
