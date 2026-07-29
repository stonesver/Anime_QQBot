from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from anime_qqbot.presentation.models import AnimeCardData, NextAiring
from anime_qqbot.presentation.renderer import AnimeCardRenderer

CJK_FONT = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
MONO_FONT = Path("/System/Library/Fonts/Menlo.ttc")


def card_data() -> AnimeCardData:
    return AnimeCardData(
        anime_id=uuid4(),
        display_title="夏日物语与一段很长但仍然应该安全换行的标题",
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
        airing_status=None,
        sources=("bangumi", "anilist", "mikan"),
        timezone_name="Asia/Shanghai",
        projection_fingerprint="fingerprint",
    )


@pytest.mark.skipif(not CJK_FONT.exists(), reason="macOS CJK font unavailable")
@pytest.mark.parametrize("poster_size", [(400, 600), (1200, 400), (300, 1200)])
async def test_renders_fixed_size_card_for_different_posters(
    tmp_path: Path,
    poster_size: tuple[int, int],
) -> None:
    poster = tmp_path / "poster.png"
    Image.new("RGB", poster_size, "#FF5D57").save(poster)
    renderer = AnimeCardRenderer(
        tmp_path / "renders",
        cjk_font_path=CJK_FONT,
        mono_font_path=MONO_FONT,
    )

    result = await renderer.render_cached(card_data(), poster)

    assert result.succeeded
    assert result.path is not None
    with Image.open(result.path) as rendered:
        assert rendered.format == "PNG"
        assert rendered.size == (1000, 600)
        assert rendered.getpixel((500, 20)) == (247, 250, 255)


@pytest.mark.skipif(not CJK_FONT.exists(), reason="macOS CJK font unavailable")
async def test_reuses_valid_cached_render(tmp_path: Path) -> None:
    poster = tmp_path / "poster.png"
    Image.new("RGB", (400, 600), "red").save(poster)
    renderer = AnimeCardRenderer(
        tmp_path / "renders",
        cjk_font_path=CJK_FONT,
        mono_font_path=MONO_FONT,
    )
    data = card_data()

    first = await renderer.render_cached(data, poster)
    poster.unlink()
    second = await renderer.render_cached(data, poster)

    assert first.path == second.path


@pytest.mark.skipif(not CJK_FONT.exists(), reason="macOS CJK font unavailable")
async def test_bad_poster_returns_failure_without_placeholder(tmp_path: Path) -> None:
    poster = tmp_path / "poster.png"
    poster.write_text("not an image", encoding="utf-8")
    renderer = AnimeCardRenderer(
        tmp_path / "renders",
        cjk_font_path=CJK_FONT,
        mono_font_path=MONO_FONT,
    )

    result = await renderer.render_cached(card_data(), poster)

    assert result.succeeded is False
    assert not list((tmp_path / "renders").rglob("*.png"))
