from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, NewType
from uuid import UUID
from zoneinfo import ZoneInfo


class SeasonName(StrEnum):
    WINTER = "冬"
    SPRING = "春"
    SUMMER = "夏"
    AUTUMN = "秋"


@dataclass(frozen=True)
class Season:
    year: int
    name: SeasonName

    @classmethod
    def from_date(cls, value: date) -> "Season":
        names = (SeasonName.WINTER, SeasonName.SPRING, SeasonName.SUMMER, SeasonName.AUTUMN)
        return cls(value.year, names[(value.month - 1) // 3])

    @property
    def date_range(self) -> tuple[date, date]:
        start_month = {
            SeasonName.WINTER: 1,
            SeasonName.SPRING: 4,
            SeasonName.SUMMER: 7,
            SeasonName.AUTUMN: 10,
        }[self.name]
        starts_on = date(self.year, start_month, 1)
        if start_month == 10:
            ends_on = date(self.year, 12, 31)
        else:
            ends_on = date(self.year, start_month + 3, 1) - timedelta(days=1)
        return starts_on, ends_on


class AnimeWeek:
    @staticmethod
    def range_containing(value: date) -> tuple[date, date]:
        starts_on = value - timedelta(days=value.weekday())
        return starts_on, starts_on + timedelta(days=6)


@dataclass(frozen=True)
class AnimeSummary:
    subject_id: int
    title_cn: str | None
    title_jp: str
    air_date: date | None
    nsfw: bool = False
    image_url: str | None = None

    @property
    def title(self) -> str:
        return self.title_cn or self.title_jp


@dataclass(frozen=True)
class AnimeDetail:
    subject_id: int
    title_cn: str | None
    title_jp: str
    air_date: date | None
    summary: str | None = None
    image_url: str | None = None
    score: float | None = None
    total_episodes: int | None = None
    nsfw: bool = False

    @property
    def title(self) -> str:
        return self.title_cn or self.title_jp

    def as_summary(self) -> AnimeSummary:
        return AnimeSummary(
            self.subject_id, self.title_cn, self.title_jp, self.air_date, self.nsfw, self.image_url
        )


@dataclass(frozen=True)
class AiringOccurrence:
    subject_id: int
    air_date: date
    air_at: datetime | None
    episode: int | None
    source: str
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.air_at is not None and self.air_at.tzinfo is None:
            raise ValueError("air_at must be timezone-aware")
        if self.updated_at is not None and self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")

    @property
    def date_only(self) -> bool:
        return self.air_at is None

    def in_timezone(self, timezone: ZoneInfo) -> datetime | None:
        return self.air_at.astimezone(timezone) if self.air_at else None


@dataclass(frozen=True)
class CatalogFreshness:
    bangumi_updated_at: datetime | None
    bangumi_data_updated_at: datetime | None
    bangumi_stale: bool
    bangumi_data_stale: bool

    @property
    def is_stale(self) -> bool:
        return self.bangumi_stale or self.bangumi_data_stale


@dataclass(frozen=True)
class CatalogListing:
    subjects: tuple[AnimeSummary, ...]
    occurrences: tuple[AiringOccurrence, ...]
    freshness: CatalogFreshness


# ---------------------------------------------------------------------------
# Multisource identity (Task 1)
# ---------------------------------------------------------------------------


# Internal IDs are immutable UUIDs. Database generates them; downstream code
# never reconstructs them from external source IDs.
AnimeId = NewType("AnimeId", UUID)
ExternalEntryId = NewType("ExternalEntryId", UUID)


class SourceName(StrEnum):
    """External sources participating in the unified catalog."""

    BANGUMI = "bangumi"
    ANILIST = "anilist"
    MIKAN = "mikan"


class LinkStatus(StrEnum):
    """Audit status for a Source Link between an Anime and an External Entry."""

    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"

    @classmethod
    def default_for_new_matches(cls) -> "LinkStatus":
        # Automated matching never starts at CONFIRMED; review must promote it.
        return cls.UNRESOLVED

    def notifies(self) -> bool:
        return self is LinkStatus.CONFIRMED

    def is_terminal_negative(self) -> bool:
        return self is LinkStatus.REJECTED


class LinkEvidenceType(StrEnum):
    """How a Source Link's evidence was collected."""

    MANUAL = "manual"
    CROSS_ID = "cross_id"
    MIKAN_BANGUMI_LINK = "mikan_bangumi_link"
    TITLE_SEASON_YEAR = "title_season_year"
    TITLE_FUZZY = "title_fuzzy"


@dataclass(frozen=True)
class ExternalEntry:
    """A row in `external_entries`: one external record, identified by source + id."""

    id: ExternalEntryId
    source: SourceName
    external_id: str
    url: str | None
    disabled: bool = False

    def __post_init__(self) -> None:
        if not self.external_id:
            raise ValueError("external_id must be a non-empty string")


@dataclass(frozen=True)
class SourceLink:
    """An audited link between an internal Anime and an External Entry."""

    external_entry_id: ExternalEntryId
    status: LinkStatus
    evidence_type: LinkEvidenceType
    confidence: float
    method: str
    created_at: datetime
    evidence: tuple[Any, ...] = field(default_factory=tuple)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0.0, 1.0]")
        if self.reviewed_at is not None and self.reviewed_at.tzinfo is None:
            raise ValueError("reviewed_at must be timezone-aware")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True)
class SourceSnapshot:
    """A versioned view of an External Entry's normalized payload."""

    external_entry_id: ExternalEntryId
    version: int
    payload: dict[str, Any]
    source_time: datetime
    fetched_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("version must be a positive integer")
        if self.source_time.tzinfo is None:
            raise ValueError("source_time must be timezone-aware")
        if self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
