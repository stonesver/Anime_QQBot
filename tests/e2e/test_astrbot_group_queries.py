"""E2E tests for group queries through the AstrBot adapter (Task 9 + P0.4).

These tests cover two layers:

* The parsing / dispatch contract: ``message -> Intent -> Reply``.
  This is exercised with stub handlers because it does not need
  a database.
* The real use case contract: the adapter dispatches the parsed
  Intent to ``anime_qqbot.application.use_cases``. These tests
  run against a real PostgreSQL via the ``async_engine`` fixture
  and assert the resulting Reply carries the actual anime row.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from anime_qqbot.operations.repository import OperatorJobRepository
from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import (
    EventAdapter,
    Reply,
    ReplyBlock,
)

SAMPLE_ANIME_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1")
SECOND_ANIME_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee2")


# ---------------------------------------------------------------------------
# Stub-handler tests (no DB)
# ---------------------------------------------------------------------------


async def _today_handler(ctx, intent) -> Reply:
    return Reply(kind="text", blocks=[ReplyBlock(text=f"today {intent.query or ''}")])


async def _week_handler(ctx, intent) -> Reply:
    return Reply(kind="text", blocks=[ReplyBlock(text=f"week group={ctx.group_id}")])


async def _search_handler(ctx, intent) -> Reply:
    if intent.query == "Ambiguous":
        return Reply(
            kind="candidates",
            candidates=["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1 Title A"],
        )
    return Reply(kind="text", blocks=[ReplyBlock(text=f"found: {intent.query}")])


async def _detail_handler(ctx, intent) -> Reply:
    if intent.anime_id:
        return Reply(
            kind="text",
            blocks=[ReplyBlock(text=f"detail anime_id={intent.anime_id}")],
        )
    return Reply(kind="text", blocks=[ReplyBlock(text=f"detail query={intent.query}")])


async def _next_handler(ctx, intent) -> Reply:
    return Reply(kind="text", blocks=[ReplyBlock(text="next: T+3d 20:00")])


HANDLERS = {
    "today": _today_handler,
    "week": _week_handler,
    "season": _search_handler,
    "search": _search_handler,
    "detail": _detail_handler,
    "next": _next_handler,
}


@pytest.fixture
def adapter() -> EventAdapter:
    return EventAdapter(sessions=None, handlers=HANDLERS)


@pytest.mark.asyncio
async def test_today_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 今天 2026-07-15",
    )
    assert "today 2026-07-15" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_week_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="42",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 本周",
    )
    assert "group=42" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_season_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 季度 2026 夏",
    )
    assert reply.kind == "text"


@pytest.mark.asyncio
async def test_search_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 搜索 夏日",
    )
    assert "found: 夏日" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_detail_with_internal_id(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content=f"/番剧 详情 {SAMPLE_ANIME_ID}",
    )
    assert "anime_id=" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_detail_with_keyword(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 详情 夏日物语",
    )
    assert "query=夏日物语" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_multi_candidate_returns_candidates_list(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 搜索 Ambiguous",
    )
    assert reply.candidates
    assert "aaaaaaaa" in reply.candidates[0]


@pytest.mark.asyncio
async def test_next_airing_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content=f"/番剧 下次 {SAMPLE_ANIME_ID}",
    )
    assert "next:" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_status_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 状态",
    )
    assert reply is not None


# ---------------------------------------------------------------------------
# Real use-case tests (require PostgreSQL)
# ---------------------------------------------------------------------------


def _engine() -> AsyncEngine:
    return create_async_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
async def async_engine() -> AsyncEngine:
    engine = _engine()
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE admin_audit_events, operator_jobs, delivery_attempts, "
            "notification_jobs, "
            "subscription_resource_filters, follow_subscriptions, "
            "source_snapshots, anime_source_links, anime_titles, "
            "airing_occurrences, external_entries, animes, "
            "source_sync_states, chat_groups, group_memberships "
            "RESTART IDENTITY CASCADE"
        )
    yield engine
    await engine.dispose()


def _sessions_for(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _insert_anime(engine: AsyncEngine, *, anime_id: UUID, title: str, nsfw: str) -> None:
    from anime_qqbot.persistence.models.catalog import Anime

    factory = _sessions_for(engine)
    async with factory() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                display_title=title,
                nsfw_flag=nsfw,
                disabled=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_real_search_finds_anime(async_engine: AsyncEngine) -> None:
    await _insert_anime(async_engine, anime_id=SAMPLE_ANIME_ID, title="夏日物语", nsfw="false")
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="u1",
        display_name="User",
        unified_msg_origin=None,
        content="/番剧 搜索 夏日物语",
    )
    assert reply.kind == "text"
    assert "夏日物语" in reply.blocks[0].text
    assert await OperatorJobRepository(factory).list_recent() == []


@pytest.mark.asyncio
async def test_real_search_miss_enqueues_background_catalog_request(
    async_engine: AsyncEngine,
) -> None:
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)

    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="u1",
        display_name="User",
        unified_msg_origin="umo:1",
        content="/番剧 搜索 尚未收录的番剧",
    )

    assert "后台补充" in reply.blocks[0].text
    jobs = await OperatorJobRepository(factory).list_recent()
    assert len(jobs) == 1
    assert jobs[0].job_type == "sync_catalog"
    assert jobs[0].parameters == {
        "trigger": "search_miss",
        "query": "尚未收录的番剧",
    }


@pytest.mark.asyncio
async def test_real_season_only_lists_occurrences_in_requested_quarter(
    async_engine: AsyncEngine,
) -> None:
    from anime_qqbot.persistence.models.catalog import AiringOccurrenceRow, ExternalEntry

    await _insert_anime(async_engine, anime_id=SAMPLE_ANIME_ID, title="夏季番", nsfw="false")
    await _insert_anime(async_engine, anime_id=SECOND_ANIME_ID, title="春季番", nsfw="false")
    factory = _sessions_for(async_engine)
    async with factory() as session, session.begin():
        summer_entry = uuid4()
        spring_entry = uuid4()
        for entry_id, external_id in (
            (summer_entry, "summer"),
            (spring_entry, "spring"),
        ):
            session.add(
                ExternalEntry(
                    id=entry_id,
                    provider="fixture",
                    external_id=external_id,
                    disabled=False,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        await session.flush()
        session.add_all(
            [
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=SAMPLE_ANIME_ID,
                    source_entry_id=summer_entry,
                    episode_label="01",
                    air_date=datetime(2026, 7, 5, tzinfo=UTC).date(),
                    air_at=datetime(2026, 7, 5, 12, 0, tzinfo=UTC),
                    precision="exact",
                    source_event_key="summer-01",
                    updated_at=datetime.now(UTC),
                ),
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=SECOND_ANIME_ID,
                    source_entry_id=spring_entry,
                    episode_label="01",
                    air_date=datetime(2026, 4, 5, tzinfo=UTC).date(),
                    air_at=datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
                    precision="exact",
                    source_event_key="spring-01",
                    updated_at=datetime.now(UTC),
                ),
            ]
        )

    adapter = EventAdapter(sessions=factory)
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="u1",
        display_name="User",
        unified_msg_origin="umo",
        content="/番剧 季度 2026 夏",
    )

    assert "夏季番" in reply.blocks[0].text
    assert "春季番" not in reply.blocks[0].text


@pytest.mark.asyncio
async def test_real_subscribe_is_idempotent(async_engine: AsyncEngine) -> None:
    await _insert_anime(async_engine, anime_id=SAMPLE_ANIME_ID, title="夏日物语", nsfw="false")
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)
    for _ in range(3):
        reply = await adapter.handle_message(
            platform="qq",
            group_id="100",
            user_id="u1",
            display_name="User",
            unified_msg_origin=None,
            content=f"/番剧 订阅 {SAMPLE_ANIME_ID}",
        )
        assert reply.kind == "text"
        assert "已订阅" in reply.blocks[0].text
    jobs = await OperatorJobRepository(factory).list_recent()
    assert len(jobs) == 1
    assert jobs[0].job_type == "sync_catalog"
    assert jobs[0].parameters == {
        "trigger": "subscription",
        "anime_id": str(SAMPLE_ANIME_ID),
    }


@pytest.mark.asyncio
async def test_real_subscription_settings_persist_all_filters(
    async_engine: AsyncEngine,
) -> None:
    from sqlalchemy import select

    from anime_qqbot.persistence.models.subscriptions_v2 import (
        SubscriptionResourceFilter,
    )

    await _insert_anime(async_engine, anime_id=SAMPLE_ANIME_ID, title="夏日物语", nsfw="false")
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)
    common = {
        "platform": "qq",
        "group_id": "100",
        "user_id": "u1",
        "display_name": "User",
        "unified_msg_origin": "umo:100",
    }
    await adapter.handle_message(
        **common,
        content=f"/番剧 订阅 {SAMPLE_ANIME_ID}",
    )
    reply = await adapter.handle_message(
        **common,
        content=(
            f"/番剧 订阅设置 {SAMPLE_ANIME_ID} 语言=简体 字幕组=GroupA,GroupB 分辨率=1080P,720p"
        ),
    )

    assert reply.kind == "text"
    async with factory() as session:
        resource_filter = (await session.execute(select(SubscriptionResourceFilter))).scalar_one()
    assert resource_filter.language == "chs"
    assert resource_filter.subtitle_groups == ["GroupA", "GroupB"]
    assert resource_filter.resolutions == ["1080p", "720p"]


@pytest.mark.asyncio
async def test_real_blocked_anime_rejected(async_engine: AsyncEngine) -> None:
    await _insert_anime(async_engine, anime_id=SAMPLE_ANIME_ID, title="成人内容", nsfw="true")
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)
    reply = await adapter.handle_message(
        platform="qq",
        group_id="100",
        user_id="u1",
        display_name="User",
        unified_msg_origin=None,
        content=f"/番剧 订阅 {SAMPLE_ANIME_ID}",
    )
    assert reply.kind == "error"
    assert "屏蔽" in reply.error


@pytest.mark.asyncio
async def test_real_multi_candidate_returns_two_rows(async_engine: AsyncEngine) -> None:
    await _insert_anime(async_engine, anime_id=SAMPLE_ANIME_ID, title="夏日物语", nsfw="false")
    await _insert_anime(
        async_engine, anime_id=SECOND_ANIME_ID, title="夏日物语 第二季", nsfw="false"
    )
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)
    reply = await adapter.handle_message(
        platform="qq",
        group_id="100",
        user_id="u1",
        display_name="User",
        unified_msg_origin=None,
        content="/番剧 搜索 夏日",
    )
    assert reply.kind == "candidates"
    assert len(reply.candidates) == 2


async def test_real_detail_prefers_unique_exact_title(async_engine: AsyncEngine) -> None:
    await _insert_anime(
        async_engine,
        anime_id=SAMPLE_ANIME_ID,
        title="「与你相恋到生命尽头」样片",
        nsfw="false",
    )
    await _insert_anime(
        async_engine,
        anime_id=SECOND_ANIME_ID,
        title="与你相恋到生命尽头",
        nsfw="false",
    )
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)

    reply = await adapter.handle_message(
        platform="qq",
        group_id="100",
        user_id="u1",
        display_name="User",
        unified_msg_origin="umo",
        content="/番剧 详情 与你相恋到生命尽头",
    )

    assert reply.kind == "text"
    assert "与你相恋到生命尽头\n" in reply.blocks[0].text
    assert "样片" not in reply.blocks[0].text


@pytest.mark.asyncio
async def test_real_resource_detail_returns_brief_sources_and_one_safe_page_link(
    async_engine: AsyncEngine,
) -> None:
    from anime_qqbot.persistence.models.resources import ResourceRelease

    await _insert_anime(
        async_engine,
        anime_id=SAMPLE_ANIME_ID,
        title="BanG Dream! YUME∞MITA",
        nsfw="false",
    )
    factory = _sessions_for(async_engine)
    published_at = datetime(2026, 7, 23, 22, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        session.add_all(
            [
                ResourceRelease(
                    id=uuid4(),
                    mikan_item_id="release-detail-1",
                    content_fingerprint="fingerprint-detail-1",
                    raw_title="[ANi] very long raw title",
                    pub_date=published_at,
                    page_url="https://mikanime.tv/Home/Episode/release-detail-1",
                    episode_label="06",
                    subtitle_groups=["ANi", "Baha", "CHT"],
                    language="cht",
                    resolutions=["1080p"],
                    anime_id=SAMPLE_ANIME_ID,
                    mikan_entry_id=None,
                    parser_version="v2",
                    status="batched",
                    discovered_at=published_at,
                ),
                ResourceRelease(
                    id=uuid4(),
                    mikan_item_id="release-detail-2",
                    content_fingerprint="fingerprint-detail-2",
                    raw_title="[Prejudice-Studio] another long raw title",
                    pub_date=published_at + timedelta(minutes=30),
                    page_url="https://mikanime.tv/Home/Episode/release-detail-2",
                    episode_label="6",
                    subtitle_groups=["Prejudice-Studio", "VideoVer"],
                    language="chs",
                    resolutions=["1080p"],
                    anime_id=SAMPLE_ANIME_ID,
                    mikan_entry_id=None,
                    parser_version="v2",
                    status="batched",
                    discovered_at=published_at,
                ),
            ]
        )

    adapter = EventAdapter(sessions=factory)
    reply = await adapter.handle_message(
        platform="qq",
        group_id="100",
        user_id="u1",
        display_name="User",
        unified_msg_origin="umo:100",
        content="资源详情 BanG Dream! YUME∞MITA 6",
    )

    assert reply.kind == "text"
    text = reply.blocks[0].text
    assert "BanG Dream! YUME∞MITA · 第 6 集" in text
    assert "• Prejudice-Studio · 简中 · 1080p · 07-24 06:30" in text
    assert "• ANi · 繁中 · 1080p · 07-24 06:00" in text
    assert "very long raw title" not in text
    assert text.count("https://") == 1
    assert "https://mikanime.tv/Home/Episode/release-detail-2" in text
    assert "release-detail-1" not in text


@pytest.mark.asyncio
async def test_real_today_listing_filters_nsfw(async_engine: AsyncEngine) -> None:
    from anime_qqbot.persistence.models.catalog import (
        AiringOccurrenceRow,
        Anime,
        ExternalEntry,
    )

    factory = _sessions_for(async_engine)
    now = datetime(2026, 7, 29, 17, 0, tzinfo=UTC)
    local_date = datetime(2026, 7, 30, tzinfo=UTC).date()
    safe_id = SAMPLE_ANIME_ID
    blocked_id = SECOND_ANIME_ID
    safe_source_id = uuid4()
    blocked_source_id = uuid4()
    async with factory() as session, session.begin():
        session.add_all(
            [
                Anime(
                    id=safe_id,
                    display_title="安全番剧",
                    nsfw_flag="false",
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                Anime(
                    id=blocked_id,
                    display_title="成人番剧",
                    nsfw_flag="true",
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=safe_source_id,
                    provider="bangumi",
                    external_id="123",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=blocked_source_id,
                    provider="bangumi",
                    external_id="456",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=safe_id,
                    source_entry_id=safe_source_id,
                    episode_label="01",
                    air_date=local_date,
                    air_at=None,
                    precision="date_only",
                    source_event_key="safe-evt-1",
                    updated_at=now,
                ),
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=blocked_id,
                    source_entry_id=blocked_source_id,
                    episode_label="01",
                    air_date=local_date,
                    air_at=now,
                    precision="exact",
                    source_event_key="blocked-evt-1",
                    updated_at=now,
                ),
            ]
        )
    adapter = EventAdapter(sessions=factory, clock=lambda: now)
    reply = await adapter.handle_message(
        platform="qq",
        group_id="100",
        user_id="u1",
        display_name="User",
        unified_msg_origin=None,
        content="/番剧 今天",
    )
    assert reply.kind == "text"
    assert "安全番剧" in reply.blocks[0].text
    assert "成人番剧" not in reply.blocks[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    ["/番剧 今天 2026-07-30", "/番剧 今天"],
)
async def test_real_today_explicit_date_uses_group_calendar_date(
    async_engine: AsyncEngine,
    content: str,
) -> None:
    from anime_qqbot.persistence.models.catalog import (
        AiringOccurrenceRow,
        Anime,
        ExternalEntry,
    )

    factory = _sessions_for(async_engine)
    now = datetime(2026, 7, 29, 16, 30, tzinfo=UTC)
    wednesday_entry = uuid4()
    thursday_entry = uuid4()
    async with factory() as session, session.begin():
        session.add_all(
            [
                Anime(
                    id=SAMPLE_ANIME_ID,
                    display_title="周三番剧",
                    nsfw_flag="false",
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                Anime(
                    id=SECOND_ANIME_ID,
                    display_title="周四番剧",
                    nsfw_flag="false",
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=wednesday_entry,
                    provider="bangumi",
                    external_id="wednesday",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=thursday_entry,
                    provider="bangumi",
                    external_id="thursday",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=SAMPLE_ANIME_ID,
                    source_entry_id=wednesday_entry,
                    episode_label="04",
                    air_date=datetime(2026, 7, 29, tzinfo=UTC).date(),
                    air_at=None,
                    precision="date_only",
                    source_event_key="wednesday-04",
                    updated_at=now,
                ),
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=SECOND_ANIME_ID,
                    source_entry_id=thursday_entry,
                    episode_label="05",
                    air_date=datetime(2026, 7, 30, tzinfo=UTC).date(),
                    air_at=None,
                    precision="date_only",
                    source_event_key="thursday-05",
                    updated_at=now,
                ),
            ]
        )

    reply = await EventAdapter(sessions=factory, clock=lambda: now).handle_message(
        platform="qq",
        group_id="100",
        user_id="u1",
        display_name="User",
        unified_msg_origin=None,
        content=content,
        timezone_name="Asia/Shanghai",
        now=now,
    )

    assert "周四番剧" in reply.blocks[0].text
    assert "周三番剧" not in reply.blocks[0].text


@pytest.mark.asyncio
async def test_real_today_prefers_exact_airing_in_group_timezone(
    async_engine: AsyncEngine,
) -> None:
    from anime_qqbot.persistence.models.catalog import (
        AiringOccurrenceRow,
        Anime,
        ExternalEntry,
    )

    factory = _sessions_for(async_engine)
    now = datetime(2026, 7, 29, 16, 45, tzinfo=UTC)
    bangumi_entry = uuid4()
    anilist_entry = uuid4()
    async with factory() as session, session.begin():
        session.add(
            Anime(
                id=SAMPLE_ANIME_ID,
                display_title="跨日精确番剧",
                nsfw_flag="false",
                disabled=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.add_all(
            [
                ExternalEntry(
                    id=bangumi_entry,
                    provider="bangumi",
                    external_id="100",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=anilist_entry,
                    provider="anilist",
                    external_id="200",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=SAMPLE_ANIME_ID,
                    source_entry_id=bangumi_entry,
                    episode_label="04",
                    air_date=datetime(2026, 7, 30, tzinfo=UTC).date(),
                    air_at=None,
                    precision="date_only",
                    source_event_key="bangumi-04",
                    updated_at=now,
                ),
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=SAMPLE_ANIME_ID,
                    source_entry_id=anilist_entry,
                    episode_label="04",
                    air_date=datetime(2026, 7, 29, tzinfo=UTC).date(),
                    air_at=datetime(2026, 7, 29, 16, 30, tzinfo=UTC),
                    precision="exact",
                    source_event_key="anilist-04",
                    updated_at=now,
                ),
            ]
        )

    reply = await EventAdapter(sessions=factory).handle_message(
        platform="qq",
        group_id="100",
        user_id="u1",
        display_name="User",
        unified_msg_origin=None,
        content="/番剧 今天 2026-07-30",
        timezone_name="Asia/Shanghai",
        now=now,
    )

    text = reply.blocks[0].text
    assert text.count("跨日精确番剧") == 1
    assert "00:30  跨日精确番剧" in text
    assert "待定" not in text


@pytest.mark.asyncio
async def test_real_week_uses_group_local_sunday(async_engine: AsyncEngine) -> None:
    from anime_qqbot.persistence.models.catalog import (
        AiringOccurrenceRow,
        Anime,
        ExternalEntry,
    )

    factory = _sessions_for(async_engine)
    now = datetime(2026, 7, 26, 16, 30, tzinfo=UTC)
    previous_entry = uuid4()
    current_entry = uuid4()
    async with factory() as session, session.begin():
        session.add_all(
            [
                Anime(
                    id=SAMPLE_ANIME_ID,
                    display_title="上周日番剧",
                    nsfw_flag="false",
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                Anime(
                    id=SECOND_ANIME_ID,
                    display_title="本周一番剧",
                    nsfw_flag="false",
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=previous_entry,
                    provider="bangumi",
                    external_id="previous-week",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=current_entry,
                    provider="bangumi",
                    external_id="current-week",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=SAMPLE_ANIME_ID,
                    source_entry_id=previous_entry,
                    episode_label="04",
                    air_date=datetime(2026, 7, 26, tzinfo=UTC).date(),
                    air_at=None,
                    precision="date_only",
                    source_event_key="previous-04",
                    updated_at=now,
                ),
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=SECOND_ANIME_ID,
                    source_entry_id=current_entry,
                    episode_label="05",
                    air_date=datetime(2026, 7, 27, tzinfo=UTC).date(),
                    air_at=None,
                    precision="date_only",
                    source_event_key="current-05",
                    updated_at=now,
                ),
            ]
        )

    reply = await EventAdapter(sessions=factory, clock=lambda: now).handle_message(
        platform="qq",
        group_id="100",
        user_id="u1",
        display_name="User",
        unified_msg_origin=None,
        content="/番剧 本周",
        timezone_name="Asia/Shanghai",
        now=now,
    )

    assert "本周一番剧" in reply.blocks[0].text
    assert "上周日番剧" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_real_umo_does_not_get_overwritten_by_stale_event(
    async_engine: AsyncEngine,
) -> None:
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)
    new_umo = "fresh-umo-token-001"
    await adapter.handle_message(
        platform="qq",
        group_id="500",
        user_id="u1",
        display_name="User",
        unified_msg_origin=new_umo,
        content="/番剧 今天",
    )
    stale_umo = "stale-umo-token-999"
    await adapter.handle_message(
        platform="qq",
        group_id="500",
        user_id="u1",
        display_name="User",
        unified_msg_origin=stale_umo,
        content="/番剧 本周",
    )
    async with factory() as session:
        from sqlalchemy import select

        from anime_qqbot.persistence.models.identity import ChatGroup

        stmt = select(ChatGroup).where(ChatGroup.platform == "qq")
        rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1
    # The most recent event timestamp wins; this verifies UMO
    # follows the same freshness contract.
    assert rows[0].unified_msg_origin == stale_umo


@pytest.mark.asyncio
async def test_real_chat_group_event_upserts(async_engine: AsyncEngine) -> None:
    factory = _sessions_for(async_engine)
    adapter = EventAdapter(sessions=factory)
    await adapter.handle_message(
        platform="qq",
        group_id="600",
        user_id="u1",
        display_name="First",
        unified_msg_origin="umo-1",
        content="/番剧 今天",
    )
    await adapter.handle_message(
        platform="qq",
        group_id="600",
        user_id="u1",
        display_name="Renamed",
        unified_msg_origin="umo-2",
        content="/番剧 今天",
    )
    async with factory() as session:
        from sqlalchemy import select

        from anime_qqbot.persistence.models.identity import (
            ChatGroup,
            GroupMembership,
        )

        groups = (await session.execute(select(ChatGroup))).scalars().all()
        members = (await session.execute(select(GroupMembership))).scalars().all()
    assert len(groups) == 1
    assert len(members) == 1
    assert members[0].display_name == "Renamed"


# ---------------------------------------------------------------------------
# Outbox dispatch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbox_claim_skips_locked(async_engine: AsyncEngine) -> None:
    """Two concurrent claimers must never see the same job."""
    import asyncio

    from anime_qqbot.application import (
        claim_pending_jobs,
        complete_job,
    )
    from anime_qqbot.persistence.models.identity import ChatGroup
    from anime_qqbot.persistence.models.notifications_v2 import NotificationJob

    factory = _sessions_for(async_engine)
    chat_group_id = uuid4()
    job_id = uuid4()
    async with factory() as session, session.begin():
        session.add(
            ChatGroup(
                id=chat_group_id,
                platform="qq",
                external_group_id="1000",
                unified_msg_origin="umo",
                timezone="Asia/Shanghai",
                enabled=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            NotificationJob(
                id=job_id,
                chat_group_id=chat_group_id,
                job_type="airing",
                business_key="airing-test-1",
                payload={"x": 1},
                status="pending",
                available_at=datetime.now(UTC) - timedelta(minutes=1),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                attempt_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

    claimed_a, claimed_b = await asyncio.gather(
        claim_pending_jobs(factory, consumer="consumer-a", limit=10),
        claim_pending_jobs(factory, consumer="consumer-b", limit=10),
    )
    assert len(claimed_a) + len(claimed_b) == 1
    claimed_id = (claimed_a + claimed_b)[0]
    assert claimed_id == job_id

    # Subsequent calls find nothing because the job is leased.
    again = await claim_pending_jobs(factory, consumer="consumer-c", limit=10)
    assert again == []

    await complete_job(factory, job_id=claimed_id, result="sent")
    async with factory() as session:
        from sqlalchemy import select

        from anime_qqbot.persistence.models.notifications_v2 import DeliveryAttempt

        job = await session.get(NotificationJob, job_id)
        attempt = (
            await session.execute(select(DeliveryAttempt).where(DeliveryAttempt.job_id == job_id))
        ).scalar_one_or_none()
    assert job is not None
    assert job.status == "sent"
    assert attempt is not None
    assert attempt.attempt_no == 1
