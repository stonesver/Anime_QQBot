from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from anime_qqbot.presentation.schedule_renderer import (
    WEEKLY_MAX_HEIGHT,
    WEEKLY_WIDTH,
    WeeklyScheduleRenderer,
)

CJK_FONT = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
MONO_FONT = Path("/System/Library/Fonts/Menlo.ttc")


def rows() -> tuple[SimpleNamespace, ...]:
    return (
        SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            display_title="夏日物语与一段很长但仍然应该被安全截断的标题",
            air_date=date(2026, 8, 3),
            air_at=datetime(2026, 8, 3, 10, tzinfo=UTC),
            episode_label="04",
        ),
        SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000002"),
            display_title="时间待定番剧",
            air_date=date(2026, 8, 5),
            air_at=None,
            episode_label="?",
        ),
    )


@pytest.mark.skipif(not CJK_FONT.exists(), reason="macOS CJK font unavailable")
async def test_renders_one_valid_weekly_png(tmp_path: Path) -> None:
    renderer = WeeklyScheduleRenderer(
        tmp_path / "weekly",
        cjk_font_path=CJK_FONT,
        mono_font_path=MONO_FONT,
    )

    result = await renderer.render_cached(
        rows(),
        timezone=ZoneInfo("Asia/Shanghai"),
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
    )

    assert result.succeeded
    assert result.path is not None
    with Image.open(result.path) as image:
        assert image.format == "PNG"
        assert image.width == WEEKLY_WIDTH
        assert 720 <= image.height <= WEEKLY_MAX_HEIGHT


@pytest.mark.skipif(not CJK_FONT.exists(), reason="macOS CJK font unavailable")
async def test_reuses_cached_weekly_png(tmp_path: Path) -> None:
    renderer = WeeklyScheduleRenderer(
        tmp_path / "weekly",
        cjk_font_path=CJK_FONT,
        mono_font_path=MONO_FONT,
    )
    kwargs = {
        "timezone": ZoneInfo("Asia/Shanghai"),
        "week_start": date(2026, 8, 3),
        "week_end": date(2026, 8, 9),
    }

    first = await renderer.render_cached(rows(), **kwargs)
    second = await renderer.render_cached(rows(), **kwargs)

    assert first.path == second.path


async def test_empty_schedule_returns_failure_without_file(tmp_path: Path) -> None:
    renderer = WeeklyScheduleRenderer.__new__(WeeklyScheduleRenderer)

    result = await renderer.render_cached(
        (),
        timezone=ZoneInfo("Asia/Shanghai"),
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
    )

    assert result.succeeded is False
    assert result.error == "empty_schedule"
