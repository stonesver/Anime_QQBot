from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeId,
    AnimeSummary,
    CatalogFreshness,
    ExternalEntry,
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


# ---------------------------------------------------------------------------
# Multisource ports (Task 1)
# ---------------------------------------------------------------------------


class SourceHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SourceHealth:
    """Health view for one external source; never contains payload or tokens."""

    status: SourceHealthStatus
    last_success: datetime | None
    last_failure: datetime | None
    last_error: str | None
    rate_limit_remaining: int | None
    retry_after: timedelta | None

    @classmethod
    def healthy(cls, *, remaining: int | None = None) -> "SourceHealth":
        return cls(
            status=SourceHealthStatus.HEALTHY,
            last_success=None,
            last_failure=None,
            last_error=None,
            rate_limit_remaining=remaining,
            retry_after=None,
        )


@dataclass(frozen=True)
class SourceSyncCursor:
    """Opaque incremental sync cursor."""

    position: str | None

    def is_terminal(self) -> bool:
        return self.position is None


@dataclass(frozen=True)
class SourceSyncDelta:
    """Incremental changes a SourceProvider yields from sync_delta()."""

    added: tuple[ExternalEntry, ...]
    updated: tuple[ExternalEntry, ...]
    removed: tuple[str, ...]
    next_cursor: str | None


@runtime_checkable
class SourceProvider(Protocol):
    """Source-agnostic port for one external provider (Bangumi / AniList / Mikan).

    Adapters MUST NOT leak httpx.Response or raw SDK objects above this seam.
    """

    async def sync_delta(self, cursor: SourceSyncCursor, limit: int) -> SourceSyncDelta: ...

    async def get_by_external_id(self, external_id: str) -> ExternalEntry | None: ...

    async def health(self) -> SourceHealth: ...


@runtime_checkable
class MultisourceCatalogStore(Protocol):
    """Reads the unified catalog using internal Anime IDs.

    External source IDs are accepted only as search filters; the store
    always returns internal Anime IDs to callers.
    """

    async def get_detail(self, anime_id: AnimeId) -> dict[str, Any] | None: ...

    async def search(self, query: str) -> list[dict[str, Any]]: ...
