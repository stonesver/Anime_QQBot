"""Integration tests for follow subscriptions and outbox (Tasks 16-19)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.application.context import ChatContext
from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository
from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.notifications.planner_v2 import AiringEvent, AiringPlanner
from anime_qqbot.presentation.subscription_presentation import SubscriptionPresentationReader
from anime_qqbot.subscriptions.repository_v2 import FollowRepository


def _engine():
    return create_async_engine(os.environ["TEST_DATABASE_URL"])


async def _reset(engine) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE delivery_attempts, notification_jobs, "
            "subscription_resource_filters, follow_subscriptions, "
            "source_snapshots, anime_source_links, "
            "anime_titles, airing_occurrences, external_entries, animes, "
            "source_sync_states, chat_groups, group_memberships "
            "RESTART IDENTITY CASCADE"
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


async def _seed_group_and_anime(session_factory) -> tuple[object, object]:
    from uuid import uuid4

    from anime_qqbot.persistence.models.identity import ChatGroup

    async with session_factory() as sess:
        g = ChatGroup(
            id=uuid4(),
            platform="qq",
            external_group_id="123",
            unified_msg_origin="umo",
            timezone="Asia/Shanghai",
            enabled=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        sess.add(g)
        await sess.commit()
        await sess.refresh(g)
    write = CatalogWriteRepository(session_factory)
    anime = await write.create_anime(display_title="Test Anime", nsfw_flag="unknown")
    return g, anime


@pytest.mark.asyncio
async def test_subscribe_and_list(session_factory) -> None:
    g, anime = await _seed_group_and_anime(session_factory)
    repo = FollowRepository(session_factory)

    sub = await repo.subscribe(chat_group_id=g.id, external_user_id="u1", anime_id=anime.id)
    assert sub.anime_id == anime.id

    mine = await repo.list_for_user(chat_group_id=g.id, external_user_id="u1")
    assert len(mine) == 1
    assert mine[0].id == sub.id


@pytest.mark.asyncio
async def test_unsubscribe_removes(session_factory) -> None:
    g, anime = await _seed_group_and_anime(session_factory)
    repo = FollowRepository(session_factory)

    await repo.subscribe(chat_group_id=g.id, external_user_id="u1", anime_id=anime.id)
    await repo.unsubscribe(chat_group_id=g.id, external_user_id="u1", anime_id=anime.id)

    mine = await repo.list_for_user(chat_group_id=g.id, external_user_id="u1")
    assert mine == []


async def test_presentation_reader_scopes_group_heat_and_viewer_state(session_factory) -> None:
    from uuid import uuid4

    from anime_qqbot.persistence.models.identity import ChatGroup

    group, anime = await _seed_group_and_anime(session_factory)
    async with session_factory() as session:
        other_group = ChatGroup(
            id=uuid4(),
            platform="qq",
            external_group_id="456",
            unified_msg_origin="other-umo",
            timezone="Asia/Shanghai",
            enabled=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(other_group)
        await session.commit()

    follow = FollowRepository(session_factory)
    await follow.subscribe(chat_group_id=group.id, external_user_id="u1", anime_id=anime.id)
    await follow.subscribe(chat_group_id=group.id, external_user_id="u2", anime_id=anime.id)
    await follow.subscribe(chat_group_id=other_group.id, external_user_id="u3", anime_id=anime.id)
    reader = SubscriptionPresentationReader(session_factory)

    first_group = await reader.read(
        ctx=ChatContext(
            platform="qq",
            group_id="123",
            user_id="u1",
            display_name="user one",
            unified_msg_origin=None,
            timezone=ZoneInfo("Asia/Shanghai"),
        ),
        anime_ids=(anime.id,),
        include_viewer_state=True,
    )
    second_group = await reader.read(
        ctx=ChatContext(
            platform="qq",
            group_id="456",
            user_id="u1",
            display_name="user one",
            unified_msg_origin=None,
            timezone=ZoneInfo("Asia/Shanghai"),
        ),
        anime_ids=(anime.id,),
        include_viewer_state=True,
    )

    assert first_group.group_follow_counts == {anime.id: 2}
    assert first_group.viewer_follows is True
    assert first_group.group_scope != second_group.group_scope
    assert first_group.viewer_scope != second_group.viewer_scope
    assert second_group.group_follow_counts == {anime.id: 1}
    assert second_group.viewer_follows is False


@pytest.mark.asyncio
async def test_nsfw_anime_rejected(session_factory) -> None:
    g, _ = await _seed_group_and_anime(session_factory)
    write = CatalogWriteRepository(session_factory)
    blocked = await write.create_anime(display_title="Blocked", nsfw_flag="true")
    repo = FollowRepository(session_factory)

    with pytest.raises(LookupError):
        await repo.subscribe(chat_group_id=g.id, external_user_id="u1", anime_id=blocked.id)


@pytest.mark.asyncio
async def test_outbox_enqueue_and_claim(session_factory) -> None:
    g, _ = await _seed_group_and_anime(session_factory)
    outbox = OutboxRepository(session_factory)

    now = datetime.now(UTC)
    await outbox.enqueue(
        chat_group_id=g.id,
        job_type="airing",
        business_key="k1",
        payload={"x": 1},
        available_at=now,
        expires_at=datetime(2027, 7, 20, tzinfo=UTC),
    )

    claimed = await outbox.claim("worker-1", limit=5)
    assert len(claimed) == 1
    assert claimed[0].status == "leased"


@pytest.mark.asyncio
async def test_outbox_dedup_key_unique(session_factory) -> None:
    g, _ = await _seed_group_and_anime(session_factory)
    outbox = OutboxRepository(session_factory)

    dt = datetime.now(UTC)
    exp = datetime(2027, 7, 27, tzinfo=UTC)
    j1 = await outbox.enqueue(
        chat_group_id=g.id,
        job_type="airing",
        business_key="k1",
        payload={},
        available_at=dt,
        expires_at=exp,
    )
    j2 = await outbox.enqueue(
        chat_group_id=g.id,
        job_type="airing",
        business_key="k1",
        payload={"dup": 2},
        available_at=dt,
        expires_at=exp,
    )
    assert j1.id == j2.id


@pytest.mark.asyncio
async def test_claim_skips_expired(session_factory) -> None:
    g, _ = await _seed_group_and_anime(session_factory)
    outbox = OutboxRepository(session_factory)

    past = datetime(2025, 1, 1, tzinfo=UTC)
    await outbox.enqueue(
        chat_group_id=g.id,
        job_type="airing",
        business_key="old",
        payload={},
        available_at=past,
        expires_at=past,
    )
    claimed = await outbox.claim("w", limit=5)
    assert claimed == []


@pytest.mark.asyncio
async def test_airing_planner_creates_jobs(session_factory) -> None:
    g, anime = await _seed_group_and_anime(session_factory)
    follow = FollowRepository(session_factory)
    outbox = OutboxRepository(session_factory)

    await follow.subscribe(chat_group_id=g.id, external_user_id="u1", anime_id=anime.id)

    planner = AiringPlanner(follow, outbox)

    # Use now() so the job is available but not yet expired.
    now = datetime.now(UTC)
    event = AiringEvent(
        anime_id=anime.id,
        episode_label="7",
        air_at=now,
        display_title="Test Anime",
    )
    created = await planner.plan_airing(event)
    assert created == 1

    claimed = await outbox.claim("worker-1", limit=5)
    assert len(claimed) == 1
    assert claimed[0].payload["episode_label"] == "7"
    assert "u1" in claimed[0].payload["at_user_ids"]
