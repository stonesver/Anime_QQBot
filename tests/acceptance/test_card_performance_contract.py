from __future__ import annotations

from pathlib import Path

import pytest

from anime_qqbot.entrypoints.card_benchmark import benchmark

CJK_FONT = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
MONO_FONT = Path("/System/Library/Fonts/Menlo.ttc")


@pytest.mark.skipif(not CJK_FONT.exists(), reason="representative local CJK font unavailable")
async def test_representative_local_render_stays_within_resource_contract() -> None:
    result = await benchmark(cjk_font=CJK_FONT, mono_font=MONO_FONT)

    assert result["success"] is True
    assert result["width"] == 1000
    assert result["height"] == 600
    assert result["first_render_seconds"] < 1.0
    assert result["rss_delta_bytes"] < 80 * 1024 * 1024
