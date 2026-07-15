from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeSummary,
    Season,
    SeasonName,
)
from anime_qqbot.catalog.sync import CatalogSyncService
from anime_qqbot.clock import FrozenClock


class FakeBangumi:
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails

    async def calendar(self) -> list[AnimeSummary]:
        if self.fails:
            raise RuntimeError("bangumi failed")
        return [AnimeSummary(1, "测试", "テスト", date(2026, 7, 1))]

    async def episodes(self, subject_id: int) -> list[AiringOccurrence]:
        del subject_id
        return []

    async def search(self, query: str) -> list[AnimeSummary]:
        del query
        return []

    async def get_detail(self, subject_id: int) -> None:
        del subject_id
        return None


class FakeData:
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails

    async def season(
        self, year: int, month: int
    ) -> tuple[list[AnimeSummary], list[AiringOccurrence]]:
        del year, month
        if self.fails:
            raise RuntimeError("data failed")
        return [], []


class RecordingRepository:
    def __init__(self) -> None:
        self.successes: list[str] = []
        self.failures: list[str] = []

    async def save_snapshot(
        self,
        provider: str,
        subjects: Sequence[AnimeSummary | AnimeDetail],
        occurrences: Sequence[AiringOccurrence],
        synced_at: datetime,
    ) -> None:
        del subjects, occurrences, synced_at
        self.successes.append(provider)

    async def record_failure(self, provider: str, error: Exception, failed_at: datetime) -> None:
        del error, failed_at
        self.failures.append(provider)


@pytest.mark.parametrize(
    ("bangumi_fails", "data_fails", "successes", "failures"),
    [
        (False, True, ["bangumi"], ["bangumi-data"]),
        (True, False, ["bangumi-data"], ["bangumi"]),
        (True, True, [], ["bangumi", "bangumi-data"]),
        (False, False, ["bangumi", "bangumi-data"], []),
    ],
)
async def test_providers_fail_independently(
    bangumi_fails: bool, data_fails: bool, successes: list[str], failures: list[str]
) -> None:
    repository = RecordingRepository()
    service = CatalogSyncService(
        FakeBangumi(bangumi_fails),
        FakeData(data_fails),
        repository,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
    )

    report = await service.sync(Season(2026, SeasonName.SUMMER))

    assert repository.successes == successes
    assert repository.failures == failures
    assert report.bangumi_ok is (not bangumi_fails)
    assert report.bangumi_data_ok is (not data_fails)
