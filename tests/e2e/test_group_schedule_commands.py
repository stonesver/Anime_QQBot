import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.commands.parser import CommandParser
from anime_qqbot.groups.permissions import PermissionPolicy
from anime_qqbot.groups.repository import GroupRepository
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


async def test_admin_can_enable_daily_schedule_but_member_cannot() -> None:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    groups = GroupRepository(sessions)
    schedules = ScheduleRepository(sessions)
    service = ScheduleAdminService(groups, schedules, PermissionPolicy())
    suffix = str(uuid4())
    admin = QQEvent(
        f"event-{suffix}",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        group_openid=f"group-{suffix}",
        member_openid="admin",
        member_role=MemberRole.ADMIN,
    )
    group_id = await groups.observe(admin)
    assert group_id is not None
    intent = CommandParser().parse("开启每日推送 09:00")

    result = await service.handle(admin, intent, datetime(2026, 7, 15, tzinfo=UTC))

    assert result.text == "每日推送已开启。"
    assert len(await schedules.list_for_group(group_id)) == 1
    member = QQEvent(
        f"member-{suffix}",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        group_openid=f"group-{suffix}",
        member_openid="member",
    )
    denied = await service.handle(member, intent, datetime.now(UTC))
    assert "只有群主" in denied.text
    await engine.dispose()
