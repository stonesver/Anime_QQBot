from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from anime_qqbot.presentation.models import AnimeCardData, NextAiring
from anime_qqbot.presentation.text import format_card_fallback


def test_fallback_contains_all_available_semantics() -> None:
    data = AnimeCardData(
        anime_id=uuid4(),
        display_title="夏日物语",
        title_jp="夏物語",
        release_year=2026,
        season_name="夏",
        media_format="TV",
        next_airing=NextAiring(
            air_date=date(2026, 7, 30),
            air_at=datetime(2026, 7, 30, 10, tzinfo=UTC),
            episode_label="04",
            precision="exact",
        ),
        bangumi_score=8.2,
        total_episodes=12,
        airing_status="放送中",
        sources=("bangumi", "anilist", "mikan"),
        timezone_name="Asia/Shanghai",
        projection_fingerprint="digest",
    )

    text = format_card_fallback(data)

    assert "夏日物语" in text
    assert "夏物語" in text
    assert "07-30 18:00" in text
    assert "第 4 集" in text
    assert "Bangumi 8.2" in text
    assert "全 12 集" in text
    assert "Bangumi / AniList / Mikan" in text
    assert "None" not in text


def test_fallback_has_no_placeholder_when_next_airing_is_unknown() -> None:
    data = AnimeCardData(
        anime_id=uuid4(),
        display_title="未知放送",
        title_jp=None,
        release_year=None,
        season_name=None,
        media_format=None,
        next_airing=None,
        bangumi_score=None,
        total_episodes=None,
        airing_status=None,
        sources=(),
        timezone_name="Asia/Shanghai",
        projection_fingerprint="digest",
    )

    text = format_card_fallback(data)

    assert "待定 · 暂无已知下一集" in text
    assert "占位" not in text
