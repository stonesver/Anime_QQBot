import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.clock import FrozenClock
from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.notifications.delivery import DeliveryRepository, NotificationDelivery
from anime_qqbot.persistence.models.notifications import DeliveryAttempt, NotificationJob
from anime_qqbot.persistence.session import create_session_factory
from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.qq.fake import FakeQQGateway


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


async def test_started_attempt_after_restart_becomes_unknown_without_resend() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    suffix = str(uuid4())
    group_id = await GroupRepository(sessions).observe(
        QQEvent(
            f"event-{suffix}",
            QQEventType.GROUP_AT_MESSAGE,
            datetime.now(UTC),
            group_openid=f"group-{suffix}",
            member_openid="member",
        )
    )
    assert group_id is not None
    now = datetime(2026, 7, 15, tzinfo=UTC)
    async with sessions() as session, session.begin():
        job = NotificationJob(
            group_id=group_id,
            business_key=f"unknown-{suffix}",
            notification_type="airing",
            payload={"group_openid": f"group-{suffix}", "text": "可能已送达"},
            status="processing",
            attempts=2,
            available_at=now,
        )
        session.add(job)
        await session.flush()
        session.add(DeliveryAttempt(job_id=job.id, attempt_no=1, status="started"))
        job_id = job.id
    gateway = FakeQQGateway()
    delivery = NotificationDelivery(DeliveryRepository(sessions), gateway, FrozenClock(now))

    assert await delivery.execute(job) == "unknown"

    async with sessions() as session:
        stored = await session.get(NotificationJob, job_id)
    assert stored is not None and stored.status == "unknown"
    assert gateway.group_messages == []
    await engine.dispose()
