import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.commands.parser import CommandParser
from anime_qqbot.groups.permissions import PermissionPolicy
from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.persistence.models.notifications import NotificationJob
from anime_qqbot.persistence.session import create_session_factory
from anime_qqbot.qq.contracts import MemberRole, QQEvent, QQEventType
from anime_qqbot.scheduling.admin import ScheduleAdminService
from anime_qqbot.scheduling.repository import ScheduleRepository


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


async def test_admin_explicitly_redelivers_unknown_job_with_operator_audit() -> None:
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
        member_openid="admin",
        member_role=MemberRole.ADMIN,
    )
    group_id = await groups.observe(event)
    assert group_id is not None
    async with sessions() as session, session.begin():
        original = NotificationJob(
            group_id=group_id,
            business_key=f"original-{suffix}",
            notification_type="airing",
            payload={"group_openid": event.group_openid, "text": "ambiguous"},
            status="unknown",
            available_at=datetime.now(UTC),
        )
        session.add(original)
        await session.flush()
        original_id = original.id
    service = ScheduleAdminService(groups, schedules, PermissionPolicy())

    status = await service.handle(event, CommandParser().parse("推送状态"), datetime.now(UTC))
    assert f"#{original_id} unknown" in status.text

    result = await service.handle(
        event, CommandParser().parse(f"补发 {original_id}"), datetime.now(UTC)
    )

    assert result.text == "已创建明确补发任务。"
    async with sessions() as session:
        redelivery = await session.scalar(
            select(NotificationJob).where(NotificationJob.notification_type == "manual_redelivery")
        )
    assert redelivery is not None and redelivery.payload["redelivery_operator"] == "admin"
    await engine.dispose()
