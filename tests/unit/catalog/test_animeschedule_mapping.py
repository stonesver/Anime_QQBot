from datetime import date, datetime
from zoneinfo import ZoneInfo

from anime_qqbot.catalog.adapters.animeschedule import AnimeScheduleCandidate
from anime_qqbot.catalog.animeschedule_mapping import (
    select_unique_exact_candidate,
    validate_cross_id_candidate,
)
from anime_qqbot.catalog.models import AnimeDetail


def candidate(
    *,
    route: str = "thunder-3",
    aliases: tuple[str, ...] = ("Thunder 3", "サンダー3"),
    anilist_id: int | None = 207254,
    year: int = 2026,
    nsfw: bool = False,
) -> AnimeScheduleCandidate:
    return AnimeScheduleCandidate(
        route=route,
        title=aliases[0],
        aliases=aliases,
        premiere=datetime(year, 7, 4, 23, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
        anilist_id=anilist_id,
        nsfw=nsfw,
        payload={},
    )


def detail(*, year: int = 2026, nsfw: bool = False) -> AnimeDetail:
    return AnimeDetail(
        subject_id=207254,
        title_cn="Thunder 3",
        title_jp="サンダー3",
        air_date=date(year, 7, 6),
        nsfw=nsfw,
        release_year=year,
    )


def test_selects_unique_normalized_exact_alias() -> None:
    result = select_unique_exact_candidate(
        [candidate()],
        ("Ｔｈｕｎｄｅｒ ３",),
    )

    assert result.candidate is not None
    assert result.reason is None


def test_rejects_multiple_exact_routes() -> None:
    result = select_unique_exact_candidate(
        [candidate(), candidate(route="thunder-3-special")],
        ("Thunder 3",),
    )

    assert result.candidate is None
    assert result.reason == "animeschedule_ambiguous"
    assert result.candidate_count == 2


def test_cross_id_accepts_different_dates_when_year_and_titles_match() -> None:
    reason = validate_cross_id_candidate(
        candidate(),
        detail(),
        known_titles=("Thunder 3",),
        bangumi_year=2026,
    )

    assert reason is None


def test_cross_id_rejects_missing_id_year_mismatch_and_nsfw() -> None:
    assert (
        validate_cross_id_candidate(
            candidate(anilist_id=None), detail(), known_titles=("Thunder 3",), bangumi_year=2026
        )
        == "animeschedule_cross_id_invalid"
    )
    assert (
        validate_cross_id_candidate(
            candidate(year=2025), detail(), known_titles=("Thunder 3",), bangumi_year=2026
        )
        == "animeschedule_year_mismatch"
    )
    assert (
        validate_cross_id_candidate(
            candidate(nsfw=True), detail(), known_titles=("Thunder 3",), bangumi_year=2026
        )
        == "animeschedule_nsfw_rejected"
    )
