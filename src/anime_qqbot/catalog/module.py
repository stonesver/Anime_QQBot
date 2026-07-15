from datetime import date, datetime

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeSummary,
    AnimeWeek,
    CatalogListing,
    Season,
)
from anime_qqbot.catalog.ports import CatalogStore


class AnimeCatalog:
    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    async def search(self, query: str) -> list[AnimeSummary]:
        return [subject for subject in await self._store.search(query) if not subject.nsfw]

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        detail = await self._store.get_detail(subject_id)
        return None if detail is None or detail.nsfw else detail

    async def list_day(self, value: date) -> CatalogListing:
        return await self._listing(value, value)

    async def list_week(self, value: date) -> CatalogListing:
        return await self._listing(*AnimeWeek.range_containing(value))

    async def list_season(self, season: Season) -> CatalogListing:
        return await self._listing(*season.date_range)

    async def get_next_airing(self, subject_id: int, *, after: datetime) -> AiringOccurrence | None:
        detail = await self.get_detail(subject_id)
        if detail is None:
            return None
        return await self._store.next_occurrence(subject_id, after)

    async def _listing(self, starts_on: date, ends_on: date) -> CatalogListing:
        subjects = [
            subject
            for subject in await self._store.subjects_between(starts_on, ends_on)
            if not subject.nsfw
        ]
        by_id = {subject.subject_id: subject for subject in subjects}
        occurrences = await self._store.occurrences_between(starts_on, ends_on)
        for subject_id in {item.subject_id for item in occurrences} - by_id.keys():
            detail = await self._store.get_detail(subject_id)
            if detail is not None and not detail.nsfw:
                by_id[subject_id] = detail.as_summary()
        occurrences = [item for item in occurrences if item.subject_id in by_id]
        return CatalogListing(
            tuple(by_id.values()), tuple(occurrences), await self._store.freshness()
        )
