import os
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.persistence.models.identity import Group
from anime_qqbot.persistence.models.runtime import ProcessedEvent


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_group_openid_is_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(Group(group_openid="group-1"))
        await session.commit()

    async with session_factory() as session:
        session.add(Group(group_openid="group-1"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_platform_event_id_is_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(ProcessedEvent(platform_event_id="event-1", event_type="GROUP_AT"))
        await session.commit()

    async with session_factory() as session:
        session.add(ProcessedEvent(platform_event_id="event-1", event_type="GROUP_AT"))
        with pytest.raises(IntegrityError):
            await session.commit()
