import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.clock import FrozenClock
from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.notifications.delivery import DeliveryRepository, NotificationDelivery
from anime_qqbot.persistence.models.notifications import DeliveryAttempt, NotificationJob
from anime_qqbot.persistence.session import create_session_factory
from anime_qqbot.qq.contracts import DeliveryOutcome, QQEvent, QQEventType
from anime_qqbot.qq.fake import FakeQQGateway


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


async def test_attempt_is_written_before_send_and_rate_limit_reschedules() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    groups = GroupRepository(sessions)
    suffix = str(uuid4())
    group_id = await groups.observe(
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
            business_key=f"delivery-{suffix}",
            notification_type="airing",
            payload={"group_openid": f"group-{suffix}", "text": "预计放送"},
            status="processing",
            attempts=1,
            available_at=now,
        )
        session.add(job)
        await session.flush()
        job_id = job.id
    gateway = FakeQQGateway()
    gateway.fail_next(DeliveryOutcome.RATE_LIMITED, retry_after_seconds=30)
    delivery = NotificationDelivery(DeliveryRepository(sessions), gateway, FrozenClock(now))

    assert await delivery.execute(job) == "pending"

    async with sessions() as session:
        stored = await session.get(NotificationJob, job_id)
        attempt = await session.scalar(
            select(DeliveryAttempt).where(DeliveryAttempt.job_id == job_id)
        )
    assert stored is not None and stored.status == "pending"
    assert attempt is not None and attempt.status == "retry"
    await engine.dispose()
