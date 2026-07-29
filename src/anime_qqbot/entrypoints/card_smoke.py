from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from PIL import Image

from anime_qqbot.presentation.models import AnimeCardData, NextAiring
from anime_qqbot.presentation.renderer import CARD_SIZE, AnimeCardRenderer

DEFAULT_CJK_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
DEFAULT_MONO_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


def sample_data() -> AnimeCardData:
    return AnimeCardData(
        anime_id=UUID("00000000-0000-0000-0000-000000000404"),
        display_title="夏日物语与银河列车的放送信号验证",
        title_jp="夏物語と銀河列車",
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
        projection_fingerprint="container-smoke",
    )


async def run_smoke(output_dir: Path, *, cjk_font: Path, mono_font: Path) -> Path:
    poster = _prepare_output(output_dir)
    renderer = AnimeCardRenderer(
        output_dir / "renders",
        cjk_font_path=cjk_font,
        mono_font_path=mono_font,
    )
    result = await renderer.render_cached(sample_data(), poster)
    if not result.succeeded or result.path is None:
        raise RuntimeError(f"card smoke failed: {result.error or 'unknown'}")
    with Image.open(result.path) as image:
        if image.format != "PNG" or image.size != CARD_SIZE:
            raise RuntimeError("card smoke generated an invalid PNG")
        image.verify()
    return result.path


def _prepare_output(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    poster = output_dir / "smoke-poster.png"
    Image.new("RGB", (900, 500), "#FF5D57").save(poster, format="PNG")
    return poster


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--cjk-font",
        default=os.environ.get("ANIME_CARD_CJK_FONT", DEFAULT_CJK_FONT),
    )
    parser.add_argument(
        "--mono-font",
        default=os.environ.get("ANIME_CARD_MONO_FONT", DEFAULT_MONO_FONT),
    )
    args = parser.parse_args()
    if args.output_dir:
        path = asyncio.run(
            run_smoke(
                Path(args.output_dir),
                cjk_font=Path(args.cjk_font),
                mono_font=Path(args.mono_font),
            )
        )
        print(path)
        return
    with tempfile.TemporaryDirectory(prefix="anime-card-smoke-") as temporary:
        path = asyncio.run(
            run_smoke(
                Path(temporary),
                cjk_font=Path(args.cjk_font),
                mono_font=Path(args.mono_font),
            )
        )
        print(f"card smoke passed: {path.name}")


if __name__ == "__main__":
    main()
