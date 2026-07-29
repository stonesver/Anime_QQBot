from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

SOURCE_ORDER = ("bangumi", "anilist", "mikan")


class CardScene(StrEnum):
    UNIQUE_SEARCH = "unique_search"
    DETAIL = "detail"
    NEXT = "next"


def card_scene_allows_image(scene: CardScene) -> bool:
    return scene in {CardScene.UNIQUE_SEARCH, CardScene.DETAIL, CardScene.NEXT}


def ordered_sources(values: set[str]) -> tuple[str, ...]:
    return tuple(source for source in SOURCE_ORDER if source in values)


@dataclass(frozen=True)
class NextAiring:
    air_date: date
    air_at: datetime | None
    episode_label: str | None
    precision: str

    def __post_init__(self) -> None:
        if self.air_at is not None and self.air_at.tzinfo is None:
            raise ValueError("air_at must be timezone-aware")


@dataclass(frozen=True)
class AnimeCardData:
    anime_id: UUID
    display_title: str
    title_jp: str | None
    release_year: int | None
    season_name: str | None
    media_format: str | None
    next_airing: NextAiring | None
    bangumi_score: float | None
    total_episodes: int | None
    airing_status: str | None
    sources: tuple[str, ...]
    timezone_name: str
    projection_fingerprint: str

    def __post_init__(self) -> None:
        if not self.display_title.strip():
            raise ValueError("display_title must not be empty")
        if self.sources != ordered_sources(set(self.sources)):
            raise ValueError("sources must be supported and ordered")
