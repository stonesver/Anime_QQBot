from __future__ import annotations

from uuid import uuid4

import pytest

from anime_qqbot.presentation.models import (
    AnimeCardData,
    CardScene,
    card_scene_allows_image,
    ordered_sources,
)


def test_only_three_explicit_scenes_allow_images() -> None:
    assert {scene.value for scene in CardScene} == {
        "unique_search",
        "detail",
        "next",
    }
    assert all(card_scene_allows_image(scene) for scene in CardScene)


def test_sources_have_deterministic_order() -> None:
    assert ordered_sources({"mikan", "bangumi", "anilist"}) == (
        "bangumi",
        "anilist",
        "mikan",
    )


def test_card_data_rejects_unordered_or_unknown_sources() -> None:
    with pytest.raises(ValueError):
        AnimeCardData(
            anime_id=uuid4(),
            display_title="夏日物语",
            title_jp=None,
            release_year=None,
            season_name=None,
            media_format=None,
            next_airing=None,
            bangumi_score=None,
            total_episodes=None,
            airing_status=None,
            sources=("mikan", "unknown"),
            timezone_name="Asia/Shanghai",
            projection_fingerprint="digest",
        )
