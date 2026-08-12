"""Strict AnimeSchedule cross-ID mapping rules."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from anime_qqbot.catalog.adapters.animeschedule import AnimeScheduleCandidate
from anime_qqbot.catalog.models import AnimeDetail


@dataclass(frozen=True)
class CandidateSelection:
    candidate: AnimeScheduleCandidate | None
    reason: str | None
    candidate_count: int


def normalize_title(title: str) -> str:
    return "".join(unicodedata.normalize("NFKC", title).casefold().split())


def normalized_titles(*values: object) -> set[str]:
    return {normalize_title(value) for value in values if isinstance(value, str) and value.strip()}


def select_unique_exact_candidate(
    candidates: list[AnimeScheduleCandidate],
    known_titles: tuple[str, ...],
) -> CandidateSelection:
    known = normalized_titles(*known_titles)
    exact_by_route = {
        candidate.route: candidate
        for candidate in candidates
        if known.intersection(normalized_titles(*candidate.aliases))
    }
    if len(exact_by_route) == 1:
        return CandidateSelection(next(iter(exact_by_route.values())), None, 1)
    if len(exact_by_route) > 1:
        return CandidateSelection(None, "animeschedule_ambiguous", len(exact_by_route))
    reason = "animeschedule_ambiguous" if candidates else "animeschedule_search_empty"
    return CandidateSelection(None, reason, len(candidates))


def validate_cross_id_candidate(
    candidate: AnimeScheduleCandidate,
    detail: AnimeDetail | None,
    *,
    known_titles: tuple[str, ...],
    bangumi_year: int | None,
) -> str | None:
    if candidate.anilist_id is None or detail is None:
        return "animeschedule_cross_id_invalid"
    if candidate.nsfw or detail.nsfw:
        return "animeschedule_nsfw_rejected"
    if not normalized_titles(*known_titles).intersection(
        normalized_titles(detail.title_cn, detail.title_jp)
    ):
        return "animeschedule_cross_id_invalid"
    years = {
        year
        for year in (bangumi_year, candidate.premiere_year, detail.release_year)
        if year is not None
    }
    if len(years) > 1:
        return "animeschedule_year_mismatch"
    return None


__all__ = [
    "CandidateSelection",
    "normalize_title",
    "normalized_titles",
    "select_unique_exact_candidate",
    "validate_cross_id_candidate",
]
