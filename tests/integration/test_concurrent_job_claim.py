import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.persistence.session import create_session_factory
from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.scheduling.repository import ScheduleRepository


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


async def test_two_workers_cannot_claim_same_job() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    groups = GroupRepository(sessions)
    schedules = ScheduleRepository(sessions)
    suffix = str(uuid4())
    event = QQEvent(
        f"event-{suffix}",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        group_openid=f"group-{suffix}",
        member_openid="member",
    )
    group_id = await groups.observe(event)
    assert group_id is not None
    now = datetime.now(UTC)
    await schedules.create_job(group_id, "airing", suffix, now, {})

    first, second = await asyncio.gather(
        schedules.claim("worker-a", now), schedules.claim("worker-b", now)
    )

    claimed = [item for item in (first, second) if item is not None]
    assert len({item.id for item in claimed}) == len(claimed)
    assert sum(item.business_key.endswith(suffix) for item in claimed) == 1
    await engine.dispose()
