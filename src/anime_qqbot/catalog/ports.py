from datetime import date, datetime
from typing import Protocol

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeSummary,
    CatalogFreshness,
)


class BangumiProvider(Protocol):
    async def search(self, query: str) -> list[AnimeSummary]: ...

    async def get_detail(self, subject_id: int) -> AnimeDetail | None: ...

    async def calendar(self) -> list[AnimeSummary]: ...

    async def episodes(self, subject_id: int) -> list[AiringOccurrence]: ...


class AiringProvider(Protocol):
    async def season(
        self, year: int, month: int
    ) -> tuple[list[AnimeSummary], list[AiringOccurrence]]: ...


class CatalogStore(Protocol):
    async def search(self, query: str) -> list[AnimeSummary]: ...

    async def get_detail(self, subject_id: int) -> AnimeDetail | None: ...

    async def occurrences_between(
        self, starts_on: date, ends_on: date
    ) -> list[AiringOccurrence]: ...

    async def subjects_between(self, starts_on: date, ends_on: date) -> list[AnimeSummary]: ...

    async def next_occurrence(
        self, subject_id: int, after: datetime
    ) -> AiringOccurrence | None: ...

    async def freshness(self) -> CatalogFreshness: ...
