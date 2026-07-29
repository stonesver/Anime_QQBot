from __future__ import annotations

import argparse
import asyncio
import json
import os
import resource
import sys
import tempfile
from pathlib import Path
from time import perf_counter
from typing import TypedDict

from anime_qqbot.entrypoints.card_smoke import (
    DEFAULT_CJK_FONT,
    DEFAULT_MONO_FONT,
    run_smoke,
)


class BenchmarkResult(TypedDict):
    success: bool
    first_render_seconds: float
    cache_render_seconds: float
    rss_delta_bytes: int
    width: int
    height: int


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


async def benchmark(*, cjk_font: Path, mono_font: Path) -> BenchmarkResult:
    with tempfile.TemporaryDirectory(prefix="anime-card-benchmark-") as temporary:
        output = Path(temporary)
        rss_before = _rss_bytes()
        first_started = perf_counter()
        first = await run_smoke(output, cjk_font=cjk_font, mono_font=mono_font)
        first_seconds = perf_counter() - first_started
        cache_started = perf_counter()
        await run_smoke(output, cjk_font=cjk_font, mono_font=mono_font)
        cache_seconds = perf_counter() - cache_started
        rss_delta = max(0, _rss_bytes() - rss_before)
        return {
            "success": first.is_file(),
            "first_render_seconds": round(first_seconds, 6),
            "cache_render_seconds": round(cache_seconds, 6),
            "rss_delta_bytes": rss_delta,
            "width": 1000,
            "height": 600,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--cjk-font",
        default=os.environ.get("ANIME_CARD_CJK_FONT", DEFAULT_CJK_FONT),
    )
    parser.add_argument(
        "--mono-font",
        default=os.environ.get("ANIME_CARD_MONO_FONT", DEFAULT_MONO_FONT),
    )
    args = parser.parse_args()
    result = asyncio.run(
        benchmark(
            cjk_font=Path(args.cjk_font),
            mono_font=Path(args.mono_font),
        )
    )
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result)
    if (
        not result["success"]
        or result["first_render_seconds"] >= 1.0
        or result["rss_delta_bytes"] >= 80 * 1024 * 1024
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
