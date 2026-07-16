import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, time
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.catalog.models import AiringOccurrence, AnimeDetail
from anime_qqbot.catalog.repository import CatalogRepository
from anime_qqbot.clock import FrozenClock
from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.notifications.planner import NotificationPlanner
from anime_qqbot.persistence.models.identity import Group
from anime_qqbot.persistence.models.notifications import GroupSchedule, NotificationJob
from anime_qqbot.persistence.session import create_session_factory
from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.scheduling.module import ScheduleSpec, ScheduleType
from anime_qqbot.scheduling.repository import ScheduleRepository


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


async def test_due_daily_schedule_creates_real_listing_and_advances_once() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    suffix = str(uuid4())
    group_openid = f"summary-group-{suffix}"
    groups = GroupRepository(sessions)
    group_id = await groups.observe(
        QQEvent(
            f"summary-event-{suffix}",
            QQEventType.GROUP_AT_MESSAGE,
            datetime(2026, 7, 15, tzinfo=UTC),
            group_openid=group_openid,
            member_openid="admin",
        )
    )
    assert group_id is not None
    async with sessions() as session, session.begin():
        await session.execute(
            update(Group).where(Group.id == group_id).values(active_messages_enabled=True)
        )

    due_at = datetime(2026, 7, 15, 1, tzinfo=UTC)
    subject_id = 200000 + uuid4().int % 100000
    await CatalogRepository(sessions, FrozenClock(due_at)).save_snapshot(
        "summary-fixture",
        [AnimeDetail(subject_id, "每日推送测试番", "Daily Test", date(2026, 7, 1))],
        [
            AiringOccurrence(
                subject_id,
                date(2026, 7, 15),
                datetime(2026, 7, 15, 12, tzinfo=UTC),
                2,
                "summary-fixture",
                due_at,
            )
        ],
        due_at,
    )
    schedules = ScheduleRepository(sessions)
    await schedules.configure(
        group_id,
        ScheduleSpec(ScheduleType.DAILY, "Asia/Shanghai", time(9)),
        datetime(2026, 7, 14, 23, tzinfo=UTC),
    )

    planner = NotificationPlanner(sessions)
    assert await planner.plan_summaries(due_at) == 1
    assert await planner.plan_summaries(due_at) == 0

    async with sessions() as session:
        job = await session.scalar(
            select(NotificationJob).where(
                NotificationJob.group_id == group_id,
                NotificationJob.business_key.like("summary:daily:%"),
            )
        )
        schedule = await session.scalar(
            select(GroupSchedule).where(GroupSchedule.group_id == group_id)
        )
    assert job is not None
    assert job.payload["group_openid"] == group_openid
    assert "2026-07-15 每日番剧" in job.payload["text"]
    assert "每日推送测试番" in job.payload["text"]
    assert schedule is not None
    assert schedule.next_run_at == datetime(2026, 7, 16, 1, tzinfo=UTC)
    await engine.dispose()


async def test_stale_daily_schedule_is_advanced_without_sending_old_summary() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    suffix = str(uuid4())
    groups = GroupRepository(sessions)
    group_id = await groups.observe(
        QQEvent(
            f"stale-event-{suffix}",
            QQEventType.GROUP_AT_MESSAGE,
            datetime(2026, 7, 10, tzinfo=UTC),
            group_openid=f"stale-summary-group-{suffix}",
            member_openid="admin",
        )
    )
    assert group_id is not None
    async with sessions() as session, session.begin():
        await session.execute(
            update(Group).where(Group.id == group_id).values(active_messages_enabled=True)
        )
    schedules = ScheduleRepository(sessions)
    await schedules.configure(
        group_id,
        ScheduleSpec(ScheduleType.DAILY, "Asia/Shanghai", time(9)),
        datetime(2026, 7, 9, tzinfo=UTC),
    )

    now = datetime(2026, 7, 15, 1, tzinfo=UTC)
    assert await NotificationPlanner(sessions).plan_summaries(now) == 0

    async with sessions() as session:
        schedule = await session.scalar(
            select(GroupSchedule).where(GroupSchedule.group_id == group_id)
        )
    assert schedule is not None and schedule.next_run_at > now
    await engine.dispose()
