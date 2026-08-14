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


def test_selects_unique_alias_when_only_trailing_punctuation_differs() -> None:
    result = select_unique_exact_candidate(
        [candidate(aliases=("鉄鍋のジャン！",))],
        ("鉄鍋のジャン",),
    )

    assert result.candidate is not None
    assert result.reason is None


def test_selects_unique_alias_when_punctuation_is_followed_by_whitespace() -> None:
    result = select_unique_exact_candidate(
        [candidate(aliases=("鉄鍋のジャン！ ",))],
        ("鉄鍋のジャン",),
    )

    assert result.candidate is not None
    assert result.reason is None


def test_selects_unique_full_title_for_a_short_main_title() -> None:
    result = select_unique_exact_candidate(
        [
            candidate(
                aliases=(
                    "最強出涸らし皇子の暗躍帝位争い "
                    "無能を演じるSSランク皇子は皇位継承戦を影から支配する",
                )
            )
        ],
        ("最強出涸らし皇子の暗躍帝位争い",),
    )

    assert result.candidate is not None
    assert result.reason is None


def test_does_not_treat_season_suffix_as_a_subtitle() -> None:
    result = select_unique_exact_candidate(
        [candidate(aliases=("Thunder 3 Season 2",))],
        ("Thunder 3",),
    )

    assert result.candidate is None
    assert result.reason == "animeschedule_ambiguous"


def test_keeps_identity_markers_strict() -> None:
    for alias in (
        "Thunder 3 Part 2",
        "Thunder 3 Cour 2",
        "Thunder 3 Movie",
        "Thunder 3 OVA",
        "Thunder 3 ONA",
        "Thunder 3 Special",
        "Thunder 3 SP",
        "Thunder 3 劇場版",
        "Thunder 3 第2期",
    ):
        result = select_unique_exact_candidate(
            [candidate(aliases=(alias,))],
            ("Thunder 3",),
        )

        assert result.candidate is None, alias


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
        bangumi_year=2026,
    )

    assert reason is None


def test_cross_id_does_not_reject_anilist_display_title_differences() -> None:
    reason = validate_cross_id_candidate(
        candidate(),
        AnimeDetail(
            subject_id=207254,
            title_cn="Different localized title",
            title_jp="Different romaji title",
            air_date=date(2026, 7, 6),
            nsfw=False,
            release_year=2026,
        ),
        bangumi_year=2026,
    )

    assert reason is None


def test_cross_id_rejects_missing_id_year_mismatch_and_nsfw() -> None:
    assert (
        validate_cross_id_candidate(candidate(anilist_id=None), detail(), bangumi_year=2026)
        == "animeschedule_cross_id_invalid"
    )
    assert (
        validate_cross_id_candidate(
            candidate(),
            AnimeDetail(
                subject_id=999,
                title_cn="Thunder 3",
                title_jp="Thunder 3",
                air_date=date(2026, 7, 6),
                nsfw=False,
                release_year=2026,
            ),
            bangumi_year=2026,
        )
        == "animeschedule_cross_id_invalid"
    )
    assert (
        validate_cross_id_candidate(candidate(year=2025), detail(), bangumi_year=2026)
        == "animeschedule_year_mismatch"
    )
    assert (
        validate_cross_id_candidate(candidate(nsfw=True), detail(), bangumi_year=2026)
        == "animeschedule_nsfw_rejected"
    )
