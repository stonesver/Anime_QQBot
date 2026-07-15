from datetime import UTC, date, datetime

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeSummary,
    CatalogFreshness,
    Season,
    SeasonName,
)
from anime_qqbot.catalog.module import AnimeCatalog


class QueryStore:
    def __init__(self) -> None:
        self.subjects = {
            1: AnimeDetail(1, "七月新番", "七月", date(2026, 7, 1)),
            2: AnimeDetail(2, None, "六月持续番", date(2026, 6, 1)),
            3: AnimeDetail(3, "过滤内容", "NSFW", date(2026, 7, 1), nsfw=True),
        }
        self.occurrences = [
            AiringOccurrence(
                1,
                date(2026, 7, 15),
                datetime(2026, 7, 15, 12, tzinfo=UTC),
                3,
                "bangumi-data",
            ),
            AiringOccurrence(2, date(2026, 7, 15), None, 7, "bangumi"),
            AiringOccurrence(3, date(2026, 7, 15), None, 1, "bangumi"),
        ]

    async def search(self, query: str) -> list[AnimeSummary]:
        del query
        return [item.as_summary() for item in self.subjects.values()]

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        return self.subjects.get(subject_id)

    async def occurrences_between(self, starts_on: date, ends_on: date) -> list[AiringOccurrence]:
        return [item for item in self.occurrences if starts_on <= item.air_date <= ends_on]

    async def subjects_between(self, starts_on: date, ends_on: date) -> list[AnimeSummary]:
        return [
            item.as_summary()
            for item in self.subjects.values()
            if item.air_date and starts_on <= item.air_date <= ends_on
        ]

    async def next_occurrence(self, subject_id: int, after: datetime) -> AiringOccurrence | None:
        return next(
            (
                item
                for item in self.occurrences
                if item.subject_id == subject_id
                and (item.air_at is None or item.air_at > after)
                and item.air_date >= after.date()
            ),
            None,
        )

    async def freshness(self) -> CatalogFreshness:
        return CatalogFreshness(None, None, True, True)


async def test_daily_query_includes_ongoing_subjects_and_filters_nsfw() -> None:
    listing = await AnimeCatalog(QueryStore()).list_day(date(2026, 7, 15))

    assert [item.subject_id for item in listing.subjects] == [1, 2]
    assert [item.subject_id for item in listing.occurrences] == [1, 2]
    assert listing.freshness.is_stale


async def test_week_and_season_boundaries() -> None:
    catalog = AnimeCatalog(QueryStore())

    week = await catalog.list_week(date(2026, 7, 15))
    season = await catalog.list_season(Season(2026, SeasonName.SUMMER))

    assert [item.subject_id for item in week.subjects] == [1, 2]
    assert [item.subject_id for item in season.subjects] == [1, 2]


async def test_next_airing_preserves_date_only_fallback() -> None:
    occurrence = await AnimeCatalog(QueryStore()).get_next_airing(
        2, after=datetime(2026, 7, 15, tzinfo=UTC)
    )

    assert occurrence is not None and occurrence.date_only
