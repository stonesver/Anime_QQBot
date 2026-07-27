"""Unit tests for the projection policy (Task 15)."""

from __future__ import annotations

from datetime import UTC, datetime

from anime_qqbot.catalog.projection import project_anime


def _ts() -> datetime:
    return datetime(2026, 7, 27, tzinfo=UTC)


def test_cn_title_prefers_bangumi_over_anilist() -> None:
    projection = project_anime(
        internal_id="aaaaaaaa",
        bangumi_snapshot={"title_cn": "夏日物语"},
        anilist_snapshot={"title_english": "Summer Tale"},
        bangumi_fetched_at=_ts(),
        anilist_fetched_at=_ts(),
    )

    assert projection.display_title is not None
    assert projection.display_title.value == "夏日物语"
    assert projection.display_title.source == "bangumi"


def test_jp_title_prefers_anilist_over_bangumi() -> None:
    projection = project_anime(
        internal_id="aaaaaaaa",
        bangumi_snapshot={"title_jp": "夏物語"},
        anilist_snapshot={"title_romaji": "Natsu Monogatari"},
        bangumi_fetched_at=_ts(),
        anilist_fetched_at=_ts(),
    )

    assert projection.title_jp is not None
    assert projection.title_jp.value == "Natsu Monogatari"
    assert projection.title_jp.source == "anilist"


def test_air_date_falls_back_to_bangumi_when_anilist_missing() -> None:
    projection = project_anime(
        internal_id="aaaaaaaa",
        bangumi_snapshot={"air_date": "2026-07-15"},
        anilist_snapshot={},
        bangumi_fetched_at=_ts(),
        anilist_fetched_at=_ts(),
    )

    assert projection.air_date is not None
    assert projection.air_date.source == "bangumi"


def test_nsfw_true_in_either_source_blocks_anime() -> None:
    projection = project_anime(
        internal_id="aaaaaaaa",
        bangumi_snapshot={"nsfw": False},
        anilist_snapshot={"nsfw": True},
        bangumi_fetched_at=_ts(),
        anilist_fetched_at=_ts(),
    )

    assert projection.nsfw_blocked is True


def test_nsfw_unknown_in_either_source_does_not_block() -> None:
    projection = project_anime(
        internal_id="aaaaaaaa",
        bangumi_snapshot={"nsfw": False},
        anilist_snapshot={"nsfw": False},
        bangumi_fetched_at=_ts(),
        anilist_fetched_at=_ts(),
    )

    assert projection.nsfw_blocked is False


def test_score_per_source() -> None:
    projection = project_anime(
        internal_id="aaaaaaaa",
        bangumi_snapshot={"score": 8.2},
        anilist_snapshot={"score": 78.0},
        bangumi_fetched_at=_ts(),
        anilist_fetched_at=_ts(),
    )

    assert projection.score_cn is not None and projection.score_cn.value == 8.2
    assert projection.score_global is not None and projection.score_global.value == 78.0


def test_disabled_anime_excluded_means_no_projection() -> None:
    # When both snapshots are missing, projection returns None fields.
    projection = project_anime(
        internal_id="aaaaaaaa",
        bangumi_snapshot=None,
        anilist_snapshot=None,
    )

    assert projection.display_title is None
    assert projection.title_jp is None
    assert projection.air_date is None
    assert projection.nsfw_blocked is False


def test_image_url_picks_bangumi_first() -> None:
    projection = project_anime(
        internal_id="aaaaaaaa",
        bangumi_snapshot={"image_url": "https://bgm/p.jpg"},
        anilist_snapshot={"image_url": "https://anilist/p.jpg"},
        bangumi_fetched_at=_ts(),
        anilist_fetched_at=_ts(),
    )

    assert projection.image_url is not None
    assert projection.image_url.source == "bangumi"
