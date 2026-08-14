from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.catalog.adapters.animeschedule import AnimeScheduleCandidate
from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind
from anime_qqbot.catalog.anilist_mapping import AniListLinkDiscoveryService
from anime_qqbot.catalog.models import AiringOccurrence, AnimeDetail, AnimeSummary
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.catalog.sync_anilist import AniListSyncService
from anime_qqbot.clock import FrozenClock
from anime_qqbot.persistence.models.catalog import (
    AniListMappingAssessment,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)


class _AniList:
    def __init__(self, detail: AnimeDetail) -> None:
        self.detail = detail
        self.fetch_calls: list[int] = []
        self.search_calls: list[str] = []

    async def fetch_media(self, anilist_id: int) -> AnimeDetail | None:
        self.fetch_calls.append(anilist_id)
        return self.detail if anilist_id == self.detail.subject_id else None

    async def search(self, query_text: str) -> list[AnimeSummary]:
        self.search_calls.append(query_text)
        return []

    async def airing_schedule(self, anilist_id: int) -> list[AiringOccurrence]:
        return []


class _AnimeSchedule:
    def __init__(
        self,
        result: list[AnimeScheduleCandidate] | ProviderError,
    ) -> None:
        self.result = result
        self.calls: list[str] = []

    async def search(self, query: str) -> list[AnimeScheduleCandidate]:
        self.calls.append(query)
        if isinstance(self.result, ProviderError):
            raise self.result
        return self.result


class _PerQueryAnimeSchedule:
    def __init__(
        self,
        results: dict[str, list[AnimeScheduleCandidate] | ProviderError],
    ) -> None:
        self.results = results
        self.calls: list[str] = []

    async def search(self, query: str) -> list[AnimeScheduleCandidate]:
        self.calls.append(query)
        result = self.results[query]
        if isinstance(result, ProviderError):
            raise result
        return result


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "TRUNCATE TABLE source_snapshots, anime_source_links, anime_titles, "
            "airing_occurrences, external_entries, animes, source_sync_states, "
            "anilist_mapping_assessments RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def seed_target(session_factory, now: datetime) -> UUID:
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
                    provider="bangumi",
                    external_id="999",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                AnimeSourceLink(
                    id=uuid4(),
                    anime_id=anime_id,
                    external_entry_id=entry_id,
                    status="confirmed",
                    evidence_type="manual",
                    confidence=1,
                    method="fixture",
                    created_at=now,
                ),
                SourceSnapshot(
                    id=uuid4(),
                    external_entry_id=entry_id,
                    version=1,
                    payload={
                        "title_jp": "Thunder 3",
                        "title_cn": "Thunder 3",
                        "air_date": "2026-07-01",
                    },
                    source_time=now,
                    fetched_at=now,
                    expires_at=None,
                ),
            ]
        )
    return anime_id


def detail() -> AnimeDetail:
    return AnimeDetail(
        subject_id=207254,
        title_cn="Thunder 3",
        title_jp="Thunder 3",
        air_date=date(2026, 7, 6),
        release_year=2026,
        nsfw=False,
    )


def candidate() -> AnimeScheduleCandidate:
    return AnimeScheduleCandidate(
        route="thunder-3",
        title="Thunder 3",
        aliases=("Thunder 3", "サンダー3"),
        premiere=datetime(2026, 7, 4, 14, 30, tzinfo=UTC),
        anilist_id=207254,
        nsfw=False,
        payload={"route": "thunder-3", "title": "Thunder 3"},
    )


async def test_cross_id_confirms_when_dates_differ_but_year_matches(session_factory) -> None:
    now = datetime(2026, 8, 12, 8, tzinfo=UTC)
    anime_id = await seed_target(session_factory, now)
    anilist = _AniList(detail())
    animeschedule = _AnimeSchedule([candidate()])
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=anilist,
        sync=AniListSyncService(
            anilist,  # type: ignore[arg-type]
            CatalogWriteRepository(session_factory),
            FrozenClock(now),
        ),
        clock=FrozenClock(now),
        animeschedule=animeschedule,
    )

    result = await discovery.run_once(limit=1, animeschedule_enabled=True)

    async with session_factory() as session:
        links = (
            await session.execute(
                select(ExternalEntry.provider, AnimeSourceLink.method)
                .join(AnimeSourceLink, AnimeSourceLink.external_entry_id == ExternalEntry.id)
                .where(AnimeSourceLink.anime_id == anime_id)
            )
        ).all()
        assessment = await session.get(AniListMappingAssessment, anime_id)
    assert result.links_confirmed == 1
    assert set(links) == {
        ("bangumi", "fixture"),
        ("anilist", "animeschedule_cross_id_v1"),
        ("animeschedule", "animeschedule_cross_id_v1"),
    }
    assert assessment is None
    assert animeschedule.calls == ["Thunder 3"]
    assert anilist.search_calls == []


async def test_server_error_records_specific_long_cooldown(session_factory) -> None:
    now = datetime(2026, 8, 12, 8, tzinfo=UTC)
    anime_id = await seed_target(session_factory, now)
    anilist = _AniList(detail())
    animeschedule = _AnimeSchedule(
        ProviderError(ProviderErrorKind.TEMPORARY, "upstream unavailable")
    )
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=anilist,
        sync=AniListSyncService(
            anilist,  # type: ignore[arg-type]
            CatalogWriteRepository(session_factory),
            FrozenClock(now),
        ),
        clock=FrozenClock(now),
        animeschedule=animeschedule,
    )

    result = await discovery.run_once(
        limit=1,
        animeschedule_enabled=True,
        animeschedule_error_cooldown_hours=168,
    )

    async with session_factory() as session:
        assessment = await session.get(AniListMappingAssessment, anime_id)
    assert result.searches_used == 1
    assert assessment is not None
    assert assessment.reason == "animeschedule_search_error"
    assert assessment.retry_after == now + timedelta(hours=168)


async def test_later_title_error_keeps_an_earlier_unique_candidate(session_factory) -> None:
    now = datetime(2026, 8, 12, 8, tzinfo=UTC)
    anime_id = await seed_target(session_factory, now)
    async with session_factory() as session, session.begin():
        snapshot = (await session.execute(select(SourceSnapshot))).scalar_one()
        snapshot.payload = {
            **snapshot.payload,
            "title_jp": "Thunder 3",
            "title_cn": "雷霆 3",
        }
    anilist = _AniList(detail())
    animeschedule = _PerQueryAnimeSchedule(
        {
            "Thunder 3": [candidate()],
            "雷霆 3": ProviderError(ProviderErrorKind.TEMPORARY, "animeschedule 500"),
        }
    )
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=anilist,
        sync=AniListSyncService(
            anilist,  # type: ignore[arg-type]
            CatalogWriteRepository(session_factory),
            FrozenClock(now),
        ),
        clock=FrozenClock(now),
        animeschedule=animeschedule,
    )

    result = await discovery.run_once(limit=2, animeschedule_enabled=True)

    async with session_factory() as session:
        assessment = await session.get(AniListMappingAssessment, anime_id)
    assert result.links_confirmed == 1
    assert result.searches_used == 2
    assert assessment is None
    assert animeschedule.calls == ["Thunder 3", "雷霆 3"]


async def test_one_successful_empty_search_is_not_recorded_as_a_source_error(
    session_factory,
) -> None:
    now = datetime(2026, 8, 12, 8, tzinfo=UTC)
    anime_id = await seed_target(session_factory, now)
    async with session_factory() as session, session.begin():
        snapshot = (await session.execute(select(SourceSnapshot))).scalar_one()
        snapshot.payload = {
            **snapshot.payload,
            "title_jp": "Thunder 3",
            "title_cn": "雷霆 3",
        }
    anilist = _AniList(detail())
    animeschedule = _PerQueryAnimeSchedule(
        {
            "Thunder 3": [],
            "雷霆 3": ProviderError(ProviderErrorKind.TEMPORARY, "animeschedule 500"),
        }
    )
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=anilist,
        sync=AniListSyncService(
            anilist,  # type: ignore[arg-type]
            CatalogWriteRepository(session_factory),
            FrozenClock(now),
        ),
        clock=FrozenClock(now),
        animeschedule=animeschedule,
    )

    await discovery.run_once(limit=2, animeschedule_enabled=True)

    async with session_factory() as session:
        assessment = await session.get(AniListMappingAssessment, anime_id)
    assert assessment is not None
    assert assessment.reason == "animeschedule_search_empty"
