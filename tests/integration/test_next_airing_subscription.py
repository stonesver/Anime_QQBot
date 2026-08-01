from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.application.context import ChatContext
from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.use_cases import subscribe
from anime_qqbot.entrypoints.cli import _plan_airing_reminders
from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)
from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.subscriptions_v2 import FollowSubscription


def _engine():
    return create_async_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
async def sessions():
    engine = _engine()
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE admin_audit_events, operator_jobs, notification_jobs, "
            "delivery_attempts, subscription_resource_filters, follow_subscriptions, "
            "source_snapshots, anime_source_links, anime_titles, airing_occurrences, "
            "external_entries, animes, source_sync_states, chat_groups, group_memberships "
            "RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed(
    sessions,
    *,
    total_episodes: int = 12,
    latest_episode: int = 4,
    next_air_at: datetime | None = None,
) -> tuple[ChatGroup, Anime]:
    now = datetime.now(UTC)
    anime_id = uuid4()
    entry_id = uuid4()
    group = ChatGroup(
        id=uuid4(),
        platform="qq",
        external_group_id="next-airing-group",
        unified_msg_origin="umo:next-airing-group",
        timezone="Asia/Shanghai",
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    anime = Anime(
        id=anime_id,
        display_title="Next Airing Test",
        nsfw_flag="unknown",
        disabled=False,
        created_at=now,
        updated_at=now,
    )
    entry = ExternalEntry(
        id=entry_id,
        provider="anilist",
        external_id="9001",
        url="https://anilist.co/anime/9001",
        disabled=False,
        created_at=now,
        updated_at=now,
    )
    link = AnimeSourceLink(
        id=uuid4(),
        anime_id=anime_id,
        external_entry_id=entry_id,
        status="confirmed",
        evidence_type="manual",
        confidence=1.0,
        method="test",
        created_at=now,
    )
    snapshot = SourceSnapshot(
        id=uuid4(),
        external_entry_id=entry_id,
        version=1,
        payload={
            "total_episodes": total_episodes,
            "status": "RELEASING",
        },
        source_time=now,
        fetched_at=now,
    )
    occurrences = [
        AiringOccurrenceRow(
            id=uuid4(),
            anime_id=anime_id,
            source_entry_id=entry_id,
            episode_label=f"{episode:02d}",
            air_date=(now - timedelta(days=episode)).date(),
            air_at=now - timedelta(days=episode),
            precision="exact",
            source_event_key=f"anilist:{episode}",
            updated_at=now,
        )
        for episode in range(1, latest_episode + 1)
    ]
    if next_air_at is not None:
        occurrences.append(
            AiringOccurrenceRow(
                id=uuid4(),
                anime_id=anime_id,
                source_entry_id=entry_id,
                episode_label=f"{latest_episode + 1:02d}",
                air_date=next_air_at.date(),
                air_at=next_air_at,
                precision="exact",
                source_event_key=f"anilist:{latest_episode + 1}",
                updated_at=now,
            )
        )
    async with sessions() as session, session.begin():
        session.add_all([group, anime, entry, link, snapshot, *occurrences])
    return group, anime


def _ctx(group: ChatGroup) -> ChatContext:
    return ChatContext(
        platform="qq",
        group_id=group.external_group_id,
        user_id="u1",
        display_name="User",
        unified_msg_origin=group.unified_msg_origin,
        timezone=ZoneInfo("Asia/Shanghai"),
        is_admin=False,
    )


@pytest.mark.asyncio
async def test_completed_anime_is_not_subscribed(sessions) -> None:
    group, anime = await _seed(sessions, total_episodes=4, latest_episode=4)

    result = await subscribe(
        sessions,
        _ctx(group),
        Intent(kind=IntentKind.SUBSCRIBE, anime_id=str(anime.id)),
    )

    assert result.success is False
    assert result.informational is True
    assert "已完结" in result.detail_message
    async with sessions() as session:
        assert (await session.execute(select(FollowSubscription))).scalars().all() == []


@pytest.mark.asyncio
async def test_unknown_next_schedule_keeps_subscription_without_airing_notice(sessions) -> None:
    group, anime = await _seed(sessions)

    result = await subscribe(
        sessions,
        _ctx(group),
        Intent(kind=IntentKind.SUBSCRIBE, anime_id=str(anime.id)),
    )

    assert result.success is True
    assert "暂未同步" in result.detail_message
    async with sessions() as session:
        assert len((await session.execute(select(FollowSubscription))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_subscribe_adds_user_to_future_pending_airing_job(sessions) -> None:
    group, anime = await _seed(
        sessions,
        next_air_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    event_at = datetime.now(UTC) + timedelta(minutes=5)
    await OutboxRepository(sessions).enqueue(
        chat_group_id=group.id,
        job_type="airing",
        business_key=f"airing/{anime.id}/05",
        payload={
            "anime_id": str(anime.id),
            "episode_label": "05",
            "air_at": event_at.isoformat(),
            "at_user_ids": [],
        },
        available_at=event_at,
        expires_at=event_at + timedelta(hours=2),
    )

    result = await subscribe(
        sessions,
        _ctx(group),
        Intent(kind=IntentKind.SUBSCRIBE, anime_id=str(anime.id)),
    )

    assert result.success is True
    async with sessions() as session:
        job = (await session.execute(select(NotificationJob))).scalar_one()
    assert job.payload["at_user_ids"] == ["u1"]


@pytest.mark.asyncio
async def test_worker_plans_only_the_earliest_future_occurrence(sessions) -> None:
    now = datetime.now(UTC)
    _group, anime = await _seed(sessions, next_air_at=now + timedelta(minutes=5))
    async with sessions() as session:
        entry_id = (
            await session.execute(
                select(AnimeSourceLink.external_entry_id).where(
                    AnimeSourceLink.anime_id == anime.id
                )
            )
        ).scalar_one()
    async with sessions() as session, session.begin():
        session.add(
            AiringOccurrenceRow(
                id=uuid4(),
                anime_id=anime.id,
                source_entry_id=entry_id,
                episode_label="06",
                air_date=(now + timedelta(minutes=7)).date(),
                air_at=now + timedelta(minutes=7),
                precision="exact",
                source_event_key="anilist:06",
                updated_at=now,
            )
        )

    class _Planner:
        def __init__(self) -> None:
            self.events = []

        async def plan_airing(self, event):
            self.events.append(event)
            return 1

    planner = _Planner()
    created = await _plan_airing_reminders(
        SimpleNamespace(sessions=sessions, planner=planner),
        now,
    )

    assert created == 1
    assert len(planner.events) == 1
    assert planner.events[0].episode_label == "05"
