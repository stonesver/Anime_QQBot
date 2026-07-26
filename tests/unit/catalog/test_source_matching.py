"""Unit tests for the auditable source matcher (Task 4)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest

from anime_qqbot.catalog.matching import (
    MatchingEvidence,
    SourceMatcher,
)
from anime_qqbot.catalog.models import (
    AnimeId,
    LinkEvidenceType,
    LinkStatus,
    SourceName,
)


@dataclass(frozen=True)
class Case:
    """One fixture scenario used to drive matcher expectations."""

    name: str
    evidence: list[MatchingEvidence]
    expected_status: LinkStatus
    expected_evidence_type: LinkEvidenceType
    expected_confidence_min: float
    expected_confidence_max: float


def _e(
    *,
    provider: SourceName,
    external_id: str,
    title: str | None = None,
    season: str | None = None,
    year: int | None = None,
    kind: str | None = None,
    episodes: int | None = None,
    cross_id: str | None = None,
) -> MatchingEvidence:
    return MatchingEvidence(
        external_provider=provider,
        external_id=external_id,
        title=title,
        season=season,
        year=year,
        kind=kind,
        episodes=episodes,
        cross_id=cross_id,
    )


CASES: list[Case] = [
    Case(
        name="explicit cross-id agreement wins",
        evidence=[
            _e(
                provider=SourceName.BANGUMI,
                external_id="42",
                title="Title A",
                year=2026,
                kind="TV",
                cross_id="anilist:99",
            ),
            _e(
                provider=SourceName.ANILIST,
                external_id="99",
                title="Title A",
                year=2026,
                kind="TV",
                cross_id="bangumi:42",
            ),
        ],
        expected_status=LinkStatus.CONFIRMED,
        expected_evidence_type=LinkEvidenceType.CROSS_ID,
        expected_confidence_min=0.95,
        expected_confidence_max=1.0,
    ),
    Case(
        name="normalized title plus season plus year plus kind matches",
        evidence=[
            _e(
                provider=SourceName.BANGUMI,
                external_id="50",
                title="  Title  B  ",
                season="summer",
                year=2026,
                kind="TV",
                episodes=12,
            ),
            _e(
                provider=SourceName.ANILIST,
                external_id="101",
                title="Title B",
                season="summer",
                year=2026,
                kind="TV",
                episodes=12,
            ),
        ],
        expected_status=LinkStatus.CONFIRMED,
        expected_evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR,
        expected_confidence_min=0.85,
        expected_confidence_max=0.95,
    ),
    Case(
        name="same title different season does not auto-confirm",
        evidence=[
            _e(
                provider=SourceName.BANGUMI,
                external_id="60",
                title="Same Title",
                season="spring",
                year=2025,
                kind="TV",
            ),
            _e(
                provider=SourceName.ANILIST,
                external_id="102",
                title="Same Title",
                season="winter",
                year=2026,
                kind="TV",
            ),
        ],
        expected_status=LinkStatus.UNRESOLVED,
        expected_evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR,
        expected_confidence_min=0.0,
        expected_confidence_max=0.5,
    ),
    Case(
        name="TV vs movie with same title is unresolved",
        evidence=[
            _e(
                provider=SourceName.BANGUMI,
                external_id="70",
                title="Movie Title",
                year=2025,
                kind="movie",
            ),
            _e(
                provider=SourceName.ANILIST,
                external_id="103",
                title="Movie Title",
                year=2025,
                kind="TV",
                episodes=12,
            ),
        ],
        expected_status=LinkStatus.UNRESOLVED,
        expected_evidence_type=LinkEvidenceType.TITLE_SEASON_YEAR,
        expected_confidence_min=0.0,
        expected_confidence_max=0.5,
    ),
    Case(
        name="low title similarity never auto-confirms",
        evidence=[
            _e(
                provider=SourceName.BANGUMI,
                external_id="80",
                title="Attack on Titan",
                year=2013,
                kind="TV",
            ),
            _e(
                provider=SourceName.ANILIST,
                external_id="104",
                title="Totally Different Show",
                year=2024,
                kind="TV",
            ),
        ],
        expected_status=LinkStatus.UNRESOLVED,
        expected_evidence_type=LinkEvidenceType.TITLE_FUZZY,
        expected_confidence_min=0.0,
        expected_confidence_max=0.4,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_matcher(case: Case) -> None:
    matcher = SourceMatcher()

    decision = matcher.evaluate(case.evidence)

    assert decision.status == case.expected_status
    assert decision.evidence_type == case.expected_evidence_type
    assert case.expected_confidence_min <= decision.confidence <= case.expected_confidence_max


def test_manual_confirmation_overrides_lower_confidence() -> None:
    matcher = SourceMatcher()
    anime_id = AnimeId(UUID("11111111-2222-3333-4444-555555555555"))

    # No usable evidence but a manual confirmation is provided.
    decision = matcher.evaluate(
        [],
        manual_confirmed_ids=[anime_id],
    )

    assert decision.status == LinkStatus.CONFIRMED
    assert decision.evidence_type == LinkEvidenceType.MANUAL
    assert decision.confidence == 1.0
    assert decision.candidate_anime_id == anime_id


def test_explicit_existing_link_is_honoured() -> None:
    matcher = SourceMatcher()
    anime_id = AnimeId(UUID("22222222-3333-4444-5555-666666666666"))

    decision = matcher.evaluate(
        [_e(provider=SourceName.BANGUMI, external_id="90", title="X")],
        manual_confirmed_ids=[anime_id],
    )

    assert decision.status == LinkStatus.CONFIRMED


def test_decision_carries_rule_version() -> None:
    matcher = SourceMatcher()

    decision = matcher.evaluate([_e(provider=SourceName.BANGUMI, external_id="42", title="X")])

    assert decision.method.startswith(SourceMatcher.RULE_VERSION)


def test_matcher_is_pure_and_deterministic() -> None:
    matcher = SourceMatcher()
    evidence = [
        _e(
            provider=SourceName.BANGUMI,
            external_id="42",
            title="Title",
            year=2026,
            kind="TV",
            season="summer",
        ),
        _e(
            provider=SourceName.ANILIST,
            external_id="99",
            title="Title",
            year=2026,
            kind="TV",
            season="summer",
        ),
    ]

    first = matcher.evaluate(evidence)
    second = matcher.evaluate(evidence)

    assert first == second


def test_matcher_does_not_touch_database(monkeypatch: pytest.MonkeyPatch) -> None:
    # A pure-computation invariant: the matcher must not import or call
    # any persistence modules. We assert by overriding the persistence
    # module and verifying no call happens during evaluation.
    import anime_qqbot.persistence.models.catalog as models

    called = {"yes": False}

    def _explode(*_args, **_kwargs):
        called["yes"] = True
        raise AssertionError("matcher must not touch the ORM")

    monkeypatch.setattr(models, "Anime", _explode)

    matcher = SourceMatcher()
    matcher.evaluate(
        [
            _e(
                provider=SourceName.BANGUMI,
                external_id="42",
                title="X",
                year=2026,
                kind="TV",
            )
        ]
    )

    assert called["yes"] is False
