from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.content_operations.planner import ContentOperationsPlanner
from anime_qqbot.content_operations.polls import PollService
from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent
from anime_qqbot.groups.settings import GroupRuntimeSettingsRepository
from anime_qqbot.persistence.models.catalog import Anime
from anime_qqbot.persistence.models.content_operations import ContentPublication
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.resources import ResourceRelease
from anime_qqbot.persistence.models.subscriptions_v2 import FollowSubscription


@pytest.fixture
async def sessions():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE content_poll_votes, content_poll_candidates, content_polls, "
            "content_publications, notification_jobs, resource_releases, "
            "follow_subscriptions, animes, group_memberships, chat_groups "
            "RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed(sessions) -> tuple[object, tuple[UUID, ...]]:
    now = datetime(2026, 8, 11, 8, tzinfo=UTC)
    group = await ChatGroupRepository(sessions).upsert_group_event(
        GroupEvent(
            platform="qq",
            external_group_id="100",
            external_user_id="owner",
            display_name="owner",
            unified_msg_origin="umo:100",
            timestamp=now,
        )
    )
    anime_ids = tuple(uuid4() for _ in range(3))
    async with sessions() as session, session.begin():
        for index, anime_id in enumerate(anime_ids, start=1):
            session.add(
                Anime(
                    id=anime_id,
                    nsfw_flag="false",
                    disabled=False,
                    display_title=f"候选{index}",
                    created_at=now,
                    updated_at=now,
                )
            )
    return group, anime_ids


async def test_group_member_can_vote_change_and_cancel_one_open_poll(sessions) -> None:
    group, anime_ids = await _seed(sessions)
    now = datetime(2026, 8, 11, 8, tzinfo=UTC)
    polls = PollService(sessions)

    opened = await polls.open_poll(
        chat_group_id=group.id,
        theme="weekly_best",
        anime_ids=anime_ids,
        period_key="2026-08-10",
        actor="owner",
        opens_at=now,
        closes_at=now + timedelta(days=2),
    )
    assert [item.title for item in opened.candidates] == ["候选1", "候选2", "候选3"]

    first = await polls.vote(
        external_group_id="100",
        external_user_id="user-1",
        position=1,
        now=now + timedelta(minutes=1),
    )
    assert first.selected_position == 1
    assert first.counts == {1: 1, 2: 0, 3: 0}

    changed = await polls.vote(
        external_group_id="100",
        external_user_id="user-1",
        position=2,
        now=now + timedelta(minutes=2),
    )
    assert changed.selected_position == 2
    assert changed.counts == {1: 0, 2: 1, 3: 0}

    assert await polls.cancel_vote(
        external_group_id="100",
        external_user_id="user-1",
        now=now + timedelta(minutes=3),
    )
    current = await polls.current(external_group_id="100", now=now + timedelta(minutes=4))
    assert current is not None
    assert current.counts == {1: 0, 2: 0, 3: 0}


async def test_poll_rejects_blocked_candidate_and_vote_after_close(sessions) -> None:
    group, anime_ids = await _seed(sessions)
    now = datetime(2026, 8, 11, 8, tzinfo=UTC)
    async with sessions() as session, session.begin():
        blocked = await session.get(Anime, anime_ids[2])
        assert blocked is not None
        blocked.nsfw_flag = "true"

    polls = PollService(sessions)
    with pytest.raises(ValueError, match="candidate"):
        await polls.open_poll(
            chat_group_id=group.id,
            theme="weekly_best",
            anime_ids=anime_ids,
            period_key="2026-08-10",
            actor="owner",
            opens_at=now,
            closes_at=now + timedelta(hours=1),
        )

    async with sessions() as session, session.begin():
        blocked = await session.get(Anime, anime_ids[2])
        assert blocked is not None
        blocked.nsfw_flag = "false"

    opened = await polls.open_poll(
        chat_group_id=group.id,
        theme="weekly_best",
        anime_ids=anime_ids,
        period_key="2026-08-11",
        actor="owner",
        opens_at=now,
        closes_at=now + timedelta(hours=1),
    )
    await polls.close_poll(opened.id, now=now + timedelta(hours=1))
    with pytest.raises(ValueError, match="no open poll"):
        await polls.vote(
            external_group_id="100",
            external_user_id="user-1",
            position=1,
            now=now + timedelta(hours=2),
        )


async def test_daily_digest_uses_actual_releases_and_is_idempotent(sessions) -> None:
    group, anime_ids = await _seed(sessions)
    now = datetime(2026, 8, 11, 14, 50, tzinfo=UTC)  # 22:50 Asia/Shanghai
    await GroupRuntimeSettingsRepository(sessions).update_policy(
        group.id,
        expected_version=1,
        now=now,
        daily_digest_enabled=True,
        daily_digest_at_all_enabled=True,
    )
    async with sessions() as session, session.begin():
        session.add(
            FollowSubscription(
                id=uuid4(),
                chat_group_id=group.id,
                external_user_id="user-1",
                anime_id=anime_ids[0],
                notify_airing=True,
                notify_resource=True,
                created_at=now - timedelta(days=1),
            )
        )
        for index, released_at in enumerate(
            (now - timedelta(minutes=30), now - timedelta(minutes=25)), start=1
        ):
            session.add(
                ResourceRelease(
                    id=uuid4(),
                    mikan_item_id=f"mikan-{index}",
                    content_fingerprint=f"fingerprint-{index}",
                    raw_title=f"资源{index}",
                    pub_date=released_at,
                    page_url=f"https://example.test/{index}",
                    episode_label="07",
                    subtitle_groups=[f"字幕组{index}"],
                    language="zh-CN",
                    resolutions=["1080P"],
                    anime_id=anime_ids[0],
                    mikan_entry_id=None,
                    parser_version="test",
                    status="matched",
                    discovered_at=released_at,
                )
            )

    planner = ContentOperationsPlanner(sessions)
    assert await planner.plan_due(now) == 1
    assert await planner.plan_due(now) == 0

    async with sessions() as session:
        jobs = (await session.execute(select(NotificationJob))).scalars().all()
        publications = (await session.execute(select(ContentPublication))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].job_type == "daily_release_digest"
    assert jobs[0].payload["at_all"] is True
    assert jobs[0].payload["items"] == [
        {
            "anime_id": str(anime_ids[0]),
            "episode_label": "07",
            "release_count": 2,
            "title": "候选1",
        }
    ]
    assert len(publications) == 1
    assert publications[0].notification_job_id == jobs[0].id


async def test_weekly_report_obeys_group_schedule_and_is_idempotent(sessions) -> None:
    group, _anime_ids = await _seed(sessions)
    now = datetime(2026, 8, 16, 12, 1, tzinfo=UTC)  # Sunday 20:01 Asia/Shanghai
    await GroupRuntimeSettingsRepository(sessions).update_policy(
        group.id,
        expected_version=1,
        now=now,
        weekly_report_enabled=True,
        weekly_report_weekday=0,
        weekly_report_minute=20 * 60,
    )

    planner = ContentOperationsPlanner(sessions)
    assert await planner.plan_due(now) == 1
    assert await planner.plan_due(now) == 0

    async with sessions() as session:
        job = (await session.execute(select(NotificationJob))).scalar_one()
    assert job.job_type == "weekly_report"
    assert job.payload["week_start"] == "2026-08-16"
    assert job.payload["timezone"] == "Asia/Shanghai"


async def test_expired_poll_is_closed_and_result_is_enqueued_once(sessions) -> None:
    group, anime_ids = await _seed(sessions)
    now = datetime(2026, 8, 11, 8, tzinfo=UTC)
    opened = await PollService(sessions).open_poll(
        chat_group_id=group.id,
        theme="group_watch",
        anime_ids=anime_ids,
        period_key="2026-08-11-expiring",
        actor="owner",
        opens_at=now,
        closes_at=now + timedelta(hours=1),
    )

    planner = ContentOperationsPlanner(sessions)
    assert await planner.plan_due(now + timedelta(hours=2)) == 1
    assert await planner.plan_due(now + timedelta(hours=2)) == 0

    closed = await PollService(sessions).get(opened.id)
    assert closed is not None
    assert closed.status == "closed"
    async with sessions() as session:
        job = (await session.execute(select(NotificationJob))).scalar_one()
    assert job.job_type == "poll_result"
