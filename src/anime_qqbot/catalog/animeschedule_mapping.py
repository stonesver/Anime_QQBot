"""Conservative title tolerance and AnimeSchedule cross-ID mapping rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from anime_qqbot.catalog.adapters.animeschedule import AnimeScheduleCandidate
from anime_qqbot.catalog.models import AnimeDetail

_EDGE_PUNCTUATION = "!！?？。．.、，,：:；;～〜~"
_SUBTITLE_SEPARATORS = " \t:：~〜～—–-「『（("
_IDENTITY_SUFFIX = re.compile(
    r"^(?:(?:season|part|cour)\s*\d|(?:movie|ova|ona|special|sp)(?:$|\s|\d))",
    re.IGNORECASE,
)
_IDENTITY_PREFIXES = (
    "第",
    "劇場版",
    "剧场版",
    "映画",
    "完結編",
    "完结篇",
)


@dataclass(frozen=True)
class CandidateSelection:
    candidate: AnimeScheduleCandidate | None
    reason: str | None
    candidate_count: int


def normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold().strip()
    normalized = normalized.strip(_EDGE_PUNCTUATION).strip()
    return "".join(normalized.split())


def normalized_titles(*values: object) -> set[str]:
    return {normalize_title(value) for value in values if isinstance(value, str) and value.strip()}


def titles_match(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if normalized_titles(*left).intersection(normalized_titles(*right)):
        return True
    return any(
        _is_main_title_extension(left_title, right_title)
        or _is_main_title_extension(right_title, left_title)
        for left_title in left
        for right_title in right
    )


def _is_main_title_extension(main_title: str, full_title: str) -> bool:
    main = _structured_title(main_title)
    full = _structured_title(full_title)
    if not main or not full.startswith(main) or len(full) == len(main):
        return False
    boundary = full[len(main)]
    if boundary not in _SUBTITLE_SEPARATORS:
        return False
    suffix = full[len(main) :].lstrip(_SUBTITLE_SEPARATORS)
    folded_suffix = suffix.casefold()
    if not suffix or suffix[0].isdigit():
        return False
    if _IDENTITY_SUFFIX.match(folded_suffix):
        return False
    return not folded_suffix.startswith(_IDENTITY_PREFIXES)


def _structured_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold().strip()
    normalized = normalized.strip(_EDGE_PUNCTUATION).strip()
    return " ".join(normalized.split())


def select_unique_exact_candidate(
    candidates: list[AnimeScheduleCandidate],
    known_titles: tuple[str, ...],
) -> CandidateSelection:
    exact_by_route = {
        candidate.route: candidate
        for candidate in candidates
        if titles_match(known_titles, candidate.aliases)
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
    bangumi_year: int | None,
) -> str | None:
    if candidate.anilist_id is None or detail is None or detail.subject_id != candidate.anilist_id:
        return "animeschedule_cross_id_invalid"
    if candidate.nsfw or detail.nsfw:
        return "animeschedule_nsfw_rejected"
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
    "titles_match",
    "validate_cross_id_candidate",
]
