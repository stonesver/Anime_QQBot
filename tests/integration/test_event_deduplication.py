import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.groups.module import GroupManager
from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.persistence.session import create_session_factory
from anime_qqbot.qq.contracts import QQEvent, QQEventType


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


@pytest.fixture
async def manager() -> AsyncIterator[tuple[GroupManager, GroupRepository]]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    repository = GroupRepository(create_session_factory(engine))
    yield GroupManager(repository), repository
    await engine.dispose()


async def test_event_is_claimed_once_and_updates_group_state(
    manager: tuple[GroupManager, GroupRepository],
) -> None:
    groups, repository = manager
    suffix = str(uuid4())
    event = QQEvent(
        f"event-{suffix}",
        QQEventType.ACTIVE_MESSAGES_ENABLED,
        datetime.now(UTC),
        group_openid=f"group-{suffix}",
        member_openid=f"member-{suffix}",
    )

    assert await groups.accept_event(event) is True
    assert await groups.accept_event(event) is False
    group = await repository.find_group(event.group_openid or "")
    assert group is not None and group.active_messages_enabled
