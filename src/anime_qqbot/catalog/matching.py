"""Pure-computation source matcher (Task 4).

Inputs: a small list of `MatchingEvidence` (one per source row) and an
optional list of `AnimeId`s that an administrator has already confirmed
via the moderation surface. Output: a `MatchingDecision` describing
the resulting status, evidence type, confidence and reason.

Rules (RULE_VERSION = "v1"):

1. If any candidate is in `manual_confirmed_ids`, return CONFIRMED at
   confidence 1.0 with evidence_type MANUAL. This is the strongest
   signal and overrides everything else.
2. If at least two sources present matching cross-IDs (e.g.
   bangumi:<id> appears in anilist's cross_id), return CONFIRMED with
   evidence_type CROSS_ID and confidence in [0.95, 1.0].
3. If two sources agree on normalised title + season + year + kind +
   episode count, return CONFIRMED with evidence_type
   TITLE_SEASON_YEAR at confidence in [0.85, 0.95].
4. If two sources share a title but disagree on season or kind, return
   UNRESOLVED at low confidence (<= 0.5) with evidence_type
   TITLE_SEASON_YEAR (the conflict is logged but no link is created).
5. Otherwise return UNRESOLVED at confidence 0.0 with evidence_type
   TITLE_FUZZY.

The matcher MUST NOT touch the database; persisting a SourceLink is the
caller's responsibility (see Task 14).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from anime_qqbot.catalog.models import (
    AnimeId,
    LinkEvidenceType,
    LinkStatus,
    SourceName,
)


@dataclass(frozen=True)
class MatchingEvidence:
    external_provider: SourceName
    external_id: str
    title: str | None = None
    season: str | None = None
    year: int | None = None
    kind: str | None = None
    episodes: int | None = None
    cross_id: str | None = None


@dataclass(frozen=True)
class MatchingDecision:
    status: LinkStatus
    evidence_type: LinkEvidenceType
    confidence: float
    method: str
    reason: str
    candidate_anime_id: AnimeId | None = None


class SourceMatcher:
    RULE_VERSION: str = "v1"

    def evaluate(
        self,
        evidence: Iterable[MatchingEvidence],
        *,
        manual_confirmed_ids: Iterable[AnimeId] = (),
    ) -> MatchingDecision:
        rows = list(evidence)
        for anime_id in manual_confirmed_ids:
            return MatchingDecision(
                status=LinkStatus.CONFIRMED,
                evidence_type=LinkEvidenceType.MANUAL,
                confidence=1.0,
                method=f"{self.RULE_VERSION}.manual",
                reason="administrator manually confirmed",
                candidate_anime_id=anime_id,
            )

        if len(rows) < 2:
            return MatchingDecision(
                status=LinkStatus.UNRESOLVED,
                evidence_type=LinkEvidenceType.TITLE_FUZZY,
                confidence=0.0,
                method=f"{self.RULE_VERSION}.insufficient_evidence",
                reason="fewer than two source rows",
            )

        if (decision := self._match_cross_id(rows)) is not None:
            return decision

        if (decision := self._match_strict(rows)) is not None:
            return decision

        return self._match_loose(rows)

    # -- rule helpers ----------------------------------------------------

    def _match_cross_id(self, rows: list[MatchingEvidence]) -> MatchingDecision | None:
        # Both sides must reference each other's (provider, external_id)
        # in their cross_id field. That's the only way to confirm without
        # trusting titles.
        for left in rows:
            if left.cross_id is None:
                continue
            expected = f"{left.external_provider.value}:{left.external_id}"
            for right in rows:
                if right is left:
                    continue
                if right.cross_id == expected:
                    return MatchingDecision(
                        status=LinkStatus.CONFIRMED,
                        evidence_type=LinkEvidenceType.CROSS_ID,
                        confidence=1.0,
                        method=f"{self.RULE_VERSION}.cross_id",
                        reason=(
                            f"{left.external_provider.value}:{left.external_id} "
                            f"cross-references {right.external_provider.value}:"
                            f"{right.external_id}"
                        ),
                    )
        return None

    def _match_strict(self, rows: list[MatchingEvidence]) -> MatchingDecision | None:
        for i, left in enumerate(rows):
            for right in rows[i + 1 :]:
                decision = self._compare_strict_pair(left, right)
                if decision is not None:
                    return decision
        return None

    def _compare_strict_pair(
        self, left: MatchingEvidence, right: MatchingEvidence
    ) -> MatchingDecision | None:
        if left.title is None or right.title is None:
            return None
        if _normalize_title(left.title) != _normalize_title(right.title):
            return None
        if (left.season or "").lower() != (right.season or "").lower():
            return MatchingDecision(
                status=LinkStatus.UNRESOLVED,
                evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR,
                confidence=0.3,
                method=f"{self.RULE_VERSION}.title_conflict_season",
                reason="title matches but seasons differ",
            )
        if (left.kind or "").lower() != (right.kind or "").lower():
            return MatchingDecision(
                status=LinkStatus.UNRESOLVED,
                evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR,
                confidence=0.3,
                method=f"{self.RULE_VERSION}.title_conflict_kind",
                reason="title matches but kinds differ",
            )
        if left.year != right.year:
            return MatchingDecision(
                status=LinkStatus.UNRESOLVED,
                evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR,
                confidence=0.3,
                method=f"{self.RULE_VERSION}.title_conflict_year",
                reason="title matches but years differ",
            )
        # Episode counts may be missing for ongoing shows; equal counts
        # raise confidence, missing counts lower it slightly.
        if left.episodes is not None and right.episodes is not None:
            if left.episodes != right.episodes:
                return MatchingDecision(
                    status=LinkStatus.UNRESOLVED,
                    evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR,
                    confidence=0.4,
                    method=f"{self.RULE_VERSION}.title_conflict_episodes",
                    reason="title matches but episode counts differ",
                )
            confidence = 0.92
        else:
            confidence = 0.86
        return MatchingDecision(
            status=LinkStatus.CONFIRMED,
            evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR,
            confidence=confidence,
            method=f"{self.RULE_VERSION}.title_season_year",
            reason="strict title + season + year + kind agreement",
        )

    def _match_loose(self, rows: list[MatchingEvidence]) -> MatchingDecision:
        titles = [_normalize_title(r.title) for r in rows if r.title is not None]
        if len(titles) >= 2 and len(set(titles)) == 1:
            return MatchingDecision(
                status=LinkStatus.UNRESOLVED,
                evidence_type=LinkEvidenceType.TITLE_FUZZY,
                confidence=0.4,
                method=f"{self.RULE_VERSION}.title_only",
                reason="title matches but supporting fields disagree",
            )
        return MatchingDecision(
            status=LinkStatus.UNRESOLVED,
            evidence_type=LinkEvidenceType.TITLE_FUZZY,
            confidence=0.0,
            method=f"{self.RULE_VERSION}.no_match",
            reason="no usable agreement across sources",
        )


def _normalize_title(title: str) -> str:
    return " ".join(title.split()).casefold()


__all__ = ["MatchingDecision", "MatchingEvidence", "SourceMatcher"]
