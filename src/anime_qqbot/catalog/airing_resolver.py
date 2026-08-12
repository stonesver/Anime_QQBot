"""Stable source priority and conflict detection for airing schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from anime_qqbot.catalog.models import AiringOccurrence

_SOURCE_PRIORITY = {
    "animeschedule": 0,
    "anilist": 1,
    "bangumi": 2,
}


def source_priority(provider: str) -> int:
    return _SOURCE_PRIORITY.get(provider, 99)


@dataclass(frozen=True)
class SourcedAiring:
    provider: str
    occurrence: AiringOccurrence


@dataclass(frozen=True)
class AiringResolution:
    selected: SourcedAiring | None
    conflict: bool
    proactive_allowed: bool
    conflicting: tuple[SourcedAiring, ...] = ()


def resolve_airing(
    candidates: list[SourcedAiring],
    *,
    conflict_threshold: timedelta = timedelta(hours=6),
) -> AiringResolution:
    if not candidates:
        return AiringResolution(None, False, False)

    ordered = sorted(
        candidates,
        key=lambda item: (
            item.occurrence.air_at is None,
            source_priority(item.provider),
            item.occurrence.air_at or item.occurrence.air_date,
        ),
    )
    exact_by_provider = {
        item.provider: item
        for item in candidates
        if item.occurrence.air_at is not None and item.provider in {"animeschedule", "anilist"}
    }
    animeschedule = exact_by_provider.get("animeschedule")
    anilist = exact_by_provider.get("anilist")
    conflict = False
    conflicting: tuple[SourcedAiring, ...] = ()
    if animeschedule is not None and anilist is not None:
        assert animeschedule.occurrence.air_at is not None
        assert anilist.occurrence.air_at is not None
        conflict = (
            abs(animeschedule.occurrence.air_at - anilist.occurrence.air_at) > conflict_threshold
        )
        if conflict:
            conflicting = (animeschedule, anilist)
    return AiringResolution(
        selected=ordered[0],
        conflict=conflict,
        proactive_allowed=not conflict,
        conflicting=conflicting,
    )


__all__ = ["AiringResolution", "SourcedAiring", "resolve_airing", "source_priority"]
