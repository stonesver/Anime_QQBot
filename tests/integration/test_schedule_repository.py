import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, time
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.groups.repository import GroupRepository
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


@pytest.fixture
async def repositories() -> AsyncIterator[tuple[GroupRepository, ScheduleRepository]]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    yield GroupRepository(sessions), ScheduleRepository(sessions)
    await engine.dispose()


async def test_schedule_upsert_and_job_business_key_are_idempotent(
    repositories: tuple[GroupRepository, ScheduleRepository],
) -> None:
    groups, schedules = repositories
    suffix = str(uuid4())
    event = QQEvent(
        f"event-{suffix}",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        group_openid=f"group-{suffix}",
        member_openid=f"member-{suffix}",
    )
    group_id = await groups.observe(event)
    assert group_id is not None
    now = datetime(2026, 7, 15, tzinfo=UTC)
    await schedules.configure(
        group_id, ScheduleSpec(ScheduleType.DAILY, "Asia/Shanghai", time(9)), now
    )
    assert await schedules.create_job(group_id, "daily", "2026-07-16", now, {})
    assert not await schedules.create_job(group_id, "daily", "2026-07-16", now, {})

    claimed = await schedules.claim("worker-1", now)
    assert claimed is not None and claimed.claimed_by == "worker-1"
