from datetime import UTC, date, datetime

import pytest

from anime_qqbot.catalog.models import AiringOccurrence, AnimeSummary, CatalogFreshness
from anime_qqbot.catalog.module import AnimeCatalog


class StubCatalogStore:
    async def search(self, query: str) -> list[AnimeSummary]:
        del query
        return [
            AnimeSummary(1, "可公开", "公開", date(2026, 7, 1)),
            AnimeSummary(2, "成人内容", "成人", date(2026, 7, 2), nsfw=True),
        ]

    async def get_detail(self, subject_id: int) -> None:
        del subject_id
        return None

    async def occurrences_between(self, starts_on: date, ends_on: date) -> list[AiringOccurrence]:
        del starts_on, ends_on
        return []

    async def subjects_between(self, starts_on: date, ends_on: date) -> list[AnimeSummary]:
        del starts_on, ends_on
        return []

    async def next_occurrence(self, subject_id: int, after: datetime) -> AiringOccurrence | None:
        del subject_id, after
        return None

    async def freshness(self) -> CatalogFreshness:
        return CatalogFreshness(None, None, False, False)


@pytest.mark.asyncio
async def test_catalog_filters_nsfw_inside_module() -> None:
    catalog = AnimeCatalog(StubCatalogStore())

    results = await catalog.search("内容")

    assert [item.subject_id for item in results] == [1]


def test_title_prefers_chinese_then_japanese() -> None:
    assert AnimeSummary(1, "中文", "日本語", None).title == "中文"
    assert AnimeSummary(2, None, "日本語", None).title == "日本語"
    assert AnimeSummary(3, "", "日本語", None).title == "日本語"


def test_occurrence_requires_timezone_when_time_is_known() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        AiringOccurrence(
            1,
            date(2026, 7, 15),
            datetime(2026, 7, 15, 20),  # noqa: DTZ001 - intentionally invalid input
            None,
            "test",
        )

    occurrence = AiringOccurrence(
        1,
        date(2026, 7, 15),
        datetime(2026, 7, 15, 20, tzinfo=UTC),
        1,
        "test",
    )
    assert occurrence.air_at == datetime(2026, 7, 15, 20, tzinfo=UTC)
