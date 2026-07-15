import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from anime_qqbot.catalog.models import AiringOccurrence, AnimeDetail
from anime_qqbot.catalog.repository import CatalogRepository
from anime_qqbot.clock import FrozenClock


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


@pytest.fixture
async def repository() -> AsyncIterator[CatalogRepository]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repo = CatalogRepository(sessions, FrozenClock(datetime(2026, 7, 15, 8, tzinfo=UTC)))
    yield repo
    await engine.dispose()


async def test_snapshot_round_trip_and_freshness(repository: CatalogRepository) -> None:
    synced_at = datetime(2026, 7, 15, 7, tzinfo=UTC)
    subject = AnimeDetail(91001, "测试番", "テスト", date(2026, 7, 1), summary="简介")
    occurrence = AiringOccurrence(
        91001, date(2026, 7, 16), datetime(2026, 7, 16, 12, tzinfo=UTC), 2, "bangumi"
    )

    await repository.save_snapshot("bangumi", [subject], [occurrence], synced_at)

    assert (await repository.get_detail(91001)) == subject
    assert (await repository.next_occurrence(91001, synced_at)) == AiringOccurrence(
        91001,
        date(2026, 7, 16),
        datetime(2026, 7, 16, 12, tzinfo=UTC),
        2,
        "bangumi",
        synced_at,
    )
    freshness = await repository.freshness()
    assert freshness.bangumi_stale is False
    assert freshness.bangumi_data_stale is True


async def test_replacing_snapshot_is_atomic(repository: CatalogRepository) -> None:
    synced_at = datetime(2026, 7, 15, tzinfo=UTC)
    subject = AnimeDetail(91002, "保留", "保持", date(2026, 7, 2))
    await repository.save_snapshot("bangumi", [subject], [], synced_at)

    invalid_occurrence = AiringOccurrence(999999, date(2026, 7, 17), None, 1, "bangumi", synced_at)
    with pytest.raises(IntegrityError):
        await repository.save_snapshot(
            "bangumi", [], [invalid_occurrence], synced_at + timedelta(hours=1)
        )

    assert await repository.get_detail(91002) == subject
