import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.catalog.models import AnimeDetail
from anime_qqbot.catalog.repository import CatalogRepository
from anime_qqbot.clock import FrozenClock
from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.persistence.session import create_session_factory
from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.subscriptions.repository import SubscriptionChange, SubscriptionRepository


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


@pytest.fixture
async def repositories() -> AsyncIterator[
    tuple[GroupRepository, CatalogRepository, SubscriptionRepository]
]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = create_session_factory(engine)
    clock = FrozenClock(datetime(2026, 7, 15, tzinfo=UTC))
    yield (
        GroupRepository(sessions),
        CatalogRepository(sessions, clock),
        SubscriptionRepository(sessions),
    )
    await engine.dispose()


async def test_subscription_is_group_scoped_idempotent_and_restorable(
    repositories: tuple[GroupRepository, CatalogRepository, SubscriptionRepository],
) -> None:
    groups, catalog, subscriptions = repositories
    suffix = str(uuid4())
    group_openid = f"group-{suffix}"
    member_openid = f"member-{suffix}"
    subject_id = 93000 + uuid4().int % 100000
    event = QQEvent(
        f"event-{suffix}",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        group_openid=group_openid,
        member_openid=member_openid,
    )
    await groups.observe(event)
    await catalog.save_snapshot(
        "bangumi",
        [AnimeDetail(subject_id, "订阅测试", "購読", date(2026, 7, 1))],
        [],
        datetime.now(UTC),
    )

    assert (
        await subscriptions.subscribe(group_openid, member_openid, subject_id)
        is SubscriptionChange.ADDED
    )
    assert (
        await subscriptions.subscribe(group_openid, member_openid, subject_id)
        is SubscriptionChange.UNCHANGED
    )
    assert (
        await subscriptions.unsubscribe(group_openid, member_openid, subject_id)
        is SubscriptionChange.DISABLED
    )
    assert (
        await subscriptions.subscribe(group_openid, member_openid, subject_id)
        is SubscriptionChange.RESTORED
    )
    assert await subscriptions.list_for_member(group_openid, member_openid) == [subject_id]
