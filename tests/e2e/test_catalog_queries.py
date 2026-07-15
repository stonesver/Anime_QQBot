import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeSummary,
    Season,
    SeasonName,
)
from anime_qqbot.catalog.module import AnimeCatalog
from anime_qqbot.catalog.repository import CatalogRepository
from anime_qqbot.catalog.sync import CatalogSyncService
from anime_qqbot.clock import FrozenClock
from anime_qqbot.persistence.session import create_session_factory


class FakeBangumi:
    async def calendar(self) -> list[AnimeSummary]:
        return [AnimeSummary(92001, "端到端番剧", "E2E", date(2026, 7, 1))]

    async def episodes(self, subject_id: int) -> list[AiringOccurrence]:
        return [AiringOccurrence(subject_id, date(2026, 7, 16), None, 3, "bangumi")]

    async def search(self, query: str) -> list[AnimeSummary]:
        del query
        return []

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        del subject_id
        return None


class FakeData:
    async def season(
        self, year: int, month: int
    ) -> tuple[list[AnimeSummary], list[AiringOccurrence]]:
        del year, month
        return (
            [AnimeSummary(92001, "端到端番剧", "E2E", date(2026, 7, 1))],
            [
                AiringOccurrence(
                    92001,
                    date(2026, 7, 16),
                    datetime(2026, 7, 16, 12, tzinfo=UTC),
                    3,
                    "bangumi-data",
                )
            ],
        )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    command.upgrade(config, "head")
    yield


@pytest.fixture
async def catalog_stack() -> AsyncIterator[tuple[CatalogSyncService, AnimeCatalog]]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    clock = FrozenClock(datetime(2026, 7, 15, 8, tzinfo=UTC))
    repository = CatalogRepository(create_session_factory(engine), clock)
    yield CatalogSyncService(FakeBangumi(), FakeData(), repository, clock), AnimeCatalog(repository)
    await engine.dispose()


async def test_sync_to_daily_weekly_seasonal_and_next_airing_queries(
    catalog_stack: tuple[CatalogSyncService, AnimeCatalog],
) -> None:
    sync, catalog = catalog_stack
    report = await sync.sync(Season(2026, SeasonName.SUMMER))

    daily = await catalog.list_day(date(2026, 7, 16))
    weekly = await catalog.list_week(date(2026, 7, 16))
    seasonal = await catalog.list_season(Season(2026, SeasonName.SUMMER))
    next_airing = await catalog.get_next_airing(92001, after=datetime(2026, 7, 15, tzinfo=UTC))

    assert report.bangumi_ok and report.bangumi_data_ok
    assert [item.title for item in daily.subjects] == ["端到端番剧"]
    assert weekly.occurrences and seasonal.subjects
    assert next_airing is not None and next_airing.source == "bangumi-data"
    assert next_airing.air_at == datetime(2026, 7, 16, 12, tzinfo=UTC)
