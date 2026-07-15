import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
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
from anime_qqbot.notifications.delivery import DeliveryRepository, NotificationDelivery
from anime_qqbot.notifications.planner import NotificationPlanner
from anime_qqbot.persistence.models.identity import Group
from anime_qqbot.persistence.models.notifications import NotificationJob
from anime_qqbot.persistence.session import create_session_factory
from anime_qqbot.qq.contracts import MemberRole, QQEvent, QQEventType
from anime_qqbot.qq.fake import FakeQQGateway
from anime_qqbot.subscriptions.repository import SubscriptionRepository


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


async def test_occurrence_plans_one_mention_message_and_delivers_it() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    suffix = str(uuid4())
    group_openid = f"group-{suffix}"
    groups = GroupRepository(sessions)
    group_id = await groups.observe(
        QQEvent(
            f"event-{suffix}",
            QQEventType.GROUP_AT_MESSAGE,
            now,
            group_openid=group_openid,
            member_openid="member-a",
            member_role=MemberRole.MEMBER,
        )
    )
    assert group_id is not None
    await groups.observe(
        QQEvent(
            f"event-b-{suffix}",
            QQEventType.GROUP_AT_MESSAGE,
            now,
            group_openid=group_openid,
            member_openid="member-b",
        )
    )
    async with sessions() as session, session.begin():
        await session.execute(
            update(Group).where(Group.id == group_id).values(active_messages_enabled=True)
        )
    subject_id = 94000 + uuid4().int % 100000
    catalog = CatalogRepository(sessions, FrozenClock(now))
    await catalog.save_snapshot(
        "bangumi-data",
        [AnimeDetail(subject_id, "定时测试番", "Scheduled", date(2026, 7, 1))],
        [AiringOccurrence(subject_id, now.date(), now, 3, "bangumi-data", now)],
        now,
    )
    subscriptions = SubscriptionRepository(sessions)
    await subscriptions.subscribe(group_openid, "member-a", subject_id)
    await subscriptions.subscribe(group_openid, "member-b", subject_id)

    assert await NotificationPlanner(sessions).plan_airing(now) == 1
    async with sessions() as session, session.begin():
        job = await session.scalar(
            select(NotificationJob).where(NotificationJob.business_key.like(f"airing:{group_id}:%"))
        )
        assert job is not None
        job.status = "processing"
        job.attempts = 1
    gateway = FakeQQGateway()
    status = await NotificationDelivery(
        DeliveryRepository(sessions), gateway, FrozenClock(now)
    ).execute(job)

    assert status == "sent"
    assert gateway.group_messages[0][1].mentions == ("member-a", "member-b")
    assert "预计放送" in gateway.group_messages[0][1].text
    await engine.dispose()
