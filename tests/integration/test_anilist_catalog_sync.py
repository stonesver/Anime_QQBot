"""Unit tests for AniList incremental sync (Task 13)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
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
    AniListMappingAssessment,
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
        self.search_calls: list[str] = []

    async def fetch_media(self, anilist_id: int) -> AnimeDetail | None:
        self.calls.append(anilist_id)
        return self._results.get(anilist_id)

    async def airing_schedule(self, anilist_id: int) -> list[AiringOccurrence]:
        return self._schedules.get(anilist_id, [])

    async def search(self, query_text: str) -> list[AnimeSummary]:
        self.search_calls.append(query_text)
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
        release_year=2026,
        season_name="夏",
        media_format="TV",
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
    assert snap.payload["release_year"] == 2026
    assert snap.payload["season_name"] == "夏"
    assert snap.payload["media_format"] == "TV"
    assert snap.payload["status"] is None


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
@pytest.mark.parametrize(
    (
        "bangumi_title_jp",
        "bangumi_title_cn",
        "candidate_native",
        "candidate_display",
        "search_title",
        "expected_searches",
    ),
    [
        (
            "対ありでした。 ～お嬢さまは格闘ゲームなんてしない～",
            "感谢对战。",
            "対ありでした。 ～お嬢さまは格闘ゲームなんてしない～",
            "Tai-Ari deshita.",
            "対ありでした。 ～お嬢さまは格闘ゲームなんてしない～",
            ("対ありでした。 ～お嬢さまは格闘ゲームなんてしない～",),
        ),
        (
            "別の日本語検索名",
            "Shared International Title",
            "別の原生題",
            "Shared International Title",
            "別の日本語検索名",
            ("別の日本語検索名",),
        ),
        (
            "検索で見つからない題",
            "Discoverable Shared Title",
            "Discoverable Shared Title",
            "Different Display Title",
            "Discoverable Shared Title",
            ("検索で見つからない題", "Discoverable Shared Title"),
        ),
    ],
)
async def test_discovery_confirms_unique_exact_known_title_and_air_date(
    session_factory,
    bangumi_title_jp: str,
    bangumi_title_cn: str,
    candidate_native: str,
    candidate_display: str,
    search_title: str,
    expected_searches: tuple[str, ...],
) -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    anime_id = uuid4()
    bangumi_entry_id = uuid4()
    candidate = AnimeSummary(
        subject_id=128757,
        title_cn=candidate_native,
        title_jp=candidate_display,
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
        searches={search_title: [candidate]},
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
                    "title_jp": bangumi_title_jp,
                    "title_cn": bangumi_title_cn,
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

    linked = await discovery.enrich_anime(anime_id)

    assert linked is True
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
    assert stub.search_calls == list(expected_searches)
    assert stub.calls == [128757]


async def _seed_discovery_target(
    session_factory,
    *,
    anime_id: UUID,
    entry_id: UUID,
    title: str,
    air_date: date,
    next_air_date: date,
    now: datetime,
) -> None:
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Anime(
                    id=anime_id,
                    nsfw_flag="false",
                    disabled=False,
                    display_title=title,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=entry_id,
                    provider="bangumi",
                    external_id=str(entry_id),
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
                    confidence=1.0,
                    method="fixture",
                    created_at=now,
                ),
                SourceSnapshot(
                    id=uuid4(),
                    external_entry_id=entry_id,
                    version=1,
                    payload={
                        "title_jp": title,
                        "title_cn": title,
                        "air_date": air_date.isoformat(),
                    },
                    source_time=now,
                    fetched_at=now,
                    expires_at=None,
                ),
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=anime_id,
                    source_entry_id=entry_id,
                    episode_label="01",
                    air_date=next_air_date,
                    air_at=None,
                    precision="date_only",
                    source_event_key=f"fixture-{anime_id}",
                    updated_at=now,
                ),
            ]
        )


@pytest.mark.asyncio
async def test_discovery_prioritizes_unmapped_shows_airing_within_seven_days(
    session_factory,
) -> None:
    now = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    near_id = UUID("00000000-0000-0000-0000-000000000002")
    later_id = UUID("00000000-0000-0000-0000-000000000001")
    await _seed_discovery_target(
        session_factory,
        anime_id=near_id,
        entry_id=uuid4(),
        title="近期优先",
        air_date=date(2026, 7, 1),
        next_air_date=date(2026, 8, 5),
        now=now,
    )
    await _seed_discovery_target(
        session_factory,
        anime_id=later_id,
        entry_id=uuid4(),
        title="目录游标靠前",
        air_date=date(2026, 7, 1),
        next_air_date=date(2026, 8, 20),
        now=now,
    )
    candidate = AnimeSummary(
        subject_id=991,
        title_cn="近期优先",
        title_jp="近期优先",
        air_date=date(2026, 7, 1),
        nsfw=False,
    )
    stub = _StubAniList({991: _detail(991)}, searches={"近期优先": [candidate]})
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=stub,
        sync=AniListSyncService(stub, CatalogWriteRepository(session_factory), FrozenClock(now)),
        clock=FrozenClock(now),
    )

    result = await discovery.run_once(limit=1)

    assert result.rows_processed == 1
    assert result.links_confirmed == 1
    assert stub.search_calls == ["近期优先"]


@pytest.mark.asyncio
async def test_discovery_accepts_a_unique_alias_with_one_day_date_difference(
    session_factory,
) -> None:
    now = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    anime_id = uuid4()
    await _seed_discovery_target(
        session_factory,
        anime_id=anime_id,
        entry_id=uuid4(),
        title="鉄鍋のジャン",
        air_date=date(2026, 7, 5),
        next_air_date=date(2026, 8, 5),
        now=now,
    )
    candidate = AnimeSummary(
        subject_id=204060,
        title_cn="鉄鍋のジャン！",
        title_jp="Tetsunabe no Jan!",
        air_date=date(2026, 7, 6),
        nsfw=False,
        title_aliases=("Tetsunabe no Jan!", "Iron Wok Jan!", "鉄鍋のジャン！"),
    )
    stub = _StubAniList(
        {204060: _detail(204060)},
        searches={"鉄鍋のジャン": [candidate]},
    )
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=stub,
        sync=AniListSyncService(stub, CatalogWriteRepository(session_factory), FrozenClock(now)),
        clock=FrozenClock(now),
    )

    result = await discovery.run_once(limit=1)

    assert result.links_confirmed == 1
    async with session_factory() as session:
        assert await session.get(AniListMappingAssessment, anime_id) is None
        link = (
            await session.execute(
                select(AnimeSourceLink)
                .join(ExternalEntry, ExternalEntry.id == AnimeSourceLink.external_entry_id)
                .where(AnimeSourceLink.anime_id == anime_id)
                .where(ExternalEntry.provider == "anilist")
            )
        ).scalar_one()
    assert link.method == "anilist_unique_title_date_tolerance_v2"
    assert link.confidence == 0.88


@pytest.mark.asyncio
async def test_discovery_rejects_a_different_season_with_the_same_date(session_factory) -> None:
    now = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    anime_id = uuid4()
    await _seed_discovery_target(
        session_factory,
        anime_id=anime_id,
        entry_id=uuid4(),
        title="Thunder 3",
        air_date=date(2026, 7, 5),
        next_air_date=date(2026, 8, 5),
        now=now,
    )
    candidate = AnimeSummary(
        subject_id=999,
        title_cn="Thunder 3 Season 2",
        title_jp="Thunder 3 Season 2",
        air_date=date(2026, 7, 5),
        nsfw=False,
        title_aliases=("Thunder 3 Season 2",),
    )
    stub = _StubAniList({}, searches={"Thunder 3": [candidate]})
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=stub,
        sync=AniListSyncService(stub, CatalogWriteRepository(session_factory), FrozenClock(now)),
        clock=FrozenClock(now),
    )

    result = await discovery.run_once(limit=1)

    assert result.links_confirmed == 0
    async with session_factory() as session:
        assessment = await session.get(AniListMappingAssessment, anime_id)
    assert assessment is not None
    assert assessment.reason == "title_not_matched"


@pytest.mark.asyncio
async def test_discovery_keeps_a_two_day_date_difference_for_review(session_factory) -> None:
    now = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    anime_id = uuid4()
    await _seed_discovery_target(
        session_factory,
        anime_id=anime_id,
        entry_id=uuid4(),
        title="日期冲突",
        air_date=date(2026, 7, 5),
        next_air_date=date(2026, 8, 5),
        now=now,
    )
    candidate = AnimeSummary(
        subject_id=998,
        title_cn="日期冲突",
        title_jp="日期冲突",
        air_date=date(2026, 7, 7),
        nsfw=False,
    )
    stub = _StubAniList({}, searches={"日期冲突": [candidate]})
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=stub,
        sync=AniListSyncService(stub, CatalogWriteRepository(session_factory), FrozenClock(now)),
        clock=FrozenClock(now),
    )

    result = await discovery.run_once(limit=1)

    assert result.links_confirmed == 0
    async with session_factory() as session:
        assessment = await session.get(AniListMappingAssessment, anime_id)
    assert assessment is not None
    assert assessment.reason == "first_air_date_mismatch"


@pytest.mark.asyncio
async def test_discovery_records_no_candidate_and_respects_retry_cooldown(session_factory) -> None:
    now = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    anime_id = uuid4()
    await _seed_discovery_target(
        session_factory,
        anime_id=anime_id,
        entry_id=uuid4(),
        title="严格匹配不到",
        air_date=date(2026, 7, 1),
        next_air_date=date(2026, 8, 5),
        now=now,
    )
    stub = _StubAniList({})
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=stub,
        sync=AniListSyncService(stub, CatalogWriteRepository(session_factory), FrozenClock(now)),
        clock=FrozenClock(now),
    )

    first = await discovery.run_once(limit=1)
    second = await discovery.run_once(limit=1)

    assert first.rows_processed == 1
    assert second.rows_processed == 0
    assert stub.search_calls == ["严格匹配不到"]
    async with session_factory() as session:
        assessment = await session.get(AniListMappingAssessment, anime_id)
    assert assessment is not None
    assert assessment.status == "no_candidate"
    assert assessment.reason == "no_search_candidate"
    assert assessment.retry_after == now + timedelta(days=1)


@pytest.mark.asyncio
async def test_discovery_caps_actual_search_requests_without_cooling_partial_row(
    session_factory,
) -> None:
    now = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    anime_id = uuid4()
    await _seed_discovery_target(
        session_factory,
        anime_id=anime_id,
        entry_id=uuid4(),
        title="日文标题",
        air_date=date(2026, 7, 1),
        next_air_date=date(2026, 8, 5),
        now=now,
    )
    async with session_factory() as session, session.begin():
        snapshot = (
            await session.execute(
                select(SourceSnapshot).where(SourceSnapshot.external_entry_id.is_not(None))
            )
        ).scalar_one()
        snapshot.payload = {**snapshot.payload, "title_cn": "中文标题"}
    stub = _StubAniList({}, searches={"日文标题": [], "中文标题": []})
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=stub,
        sync=AniListSyncService(stub, CatalogWriteRepository(session_factory), FrozenClock(now)),
        clock=FrozenClock(now),
    )

    result = await discovery.run_once(limit=1)

    assert result.rows_processed == 0
    assert result.searches_used == 1
    assert result.rows_deferred == 1
    assert stub.search_calls == ["日文标题"]
    async with session_factory() as session:
        assert await session.get(AniListMappingAssessment, anime_id) is None


@pytest.mark.asyncio
async def test_discovery_uses_configured_retry_cooldown(session_factory) -> None:
    now = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)
    anime_id = uuid4()
    await _seed_discovery_target(
        session_factory,
        anime_id=anime_id,
        entry_id=uuid4(),
        title="可调冷却",
        air_date=date(2026, 7, 1),
        next_air_date=date(2026, 8, 5),
        now=now,
    )
    stub = _StubAniList({})
    discovery = AniListLinkDiscoveryService(
        sessions=session_factory,
        anilist=stub,
        sync=AniListSyncService(stub, CatalogWriteRepository(session_factory), FrozenClock(now)),
        clock=FrozenClock(now),
    )

    await discovery.run_once(limit=1, retry_cooldown_hours=2)

    async with session_factory() as session:
        assessment = await session.get(AniListMappingAssessment, anime_id)
    assert assessment is not None
    assert assessment.retry_after == now + timedelta(hours=2)
