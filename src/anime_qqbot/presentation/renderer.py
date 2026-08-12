from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont, UnidentifiedImageError
from PIL.ImageFont import FreeTypeFont

from anime_qqbot.presentation.models import AnimeCardData

logger = logging.getLogger(__name__)

CARD_SIZE = (1000, 600)
POSTER_SIZE = (400, 600)
PAPER = "#F7FAFF"
SIGNAL_BLUE = "#365FC7"
ON_AIR_RED = "#FF5D57"
FOLLOW_GOLD = "#E6B65B"
INK = "#17223B"
MIST_BLUE = "#E9EFFD"


@dataclass(frozen=True)
class RenderResult:
    path: Path | None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.path is not None


class AnimeCardRenderer:
    def __init__(
        self,
        render_root: Path,
        *,
        cjk_font_path: Path,
        mono_font_path: Path,
    ) -> None:
        self._render_root = render_root
        self._cjk_font_path = cjk_font_path
        self._mono_font_path = mono_font_path
        self._semaphore = asyncio.Semaphore(1)
        self._validate_fonts()

    async def render_cached(
        self,
        data: AnimeCardData,
        poster_path: Path,
        *,
        viewer_follows: bool = False,
        viewer_scope: str | None = None,
    ) -> RenderResult:
        output_dir = self._render_root / str(data.anime_id)
        output_path = output_dir / f"{_cache_fingerprint(data, viewer_follows, viewer_scope)}.png"
        if _valid_cached_png(output_path):
            os.utime(output_path, None)
            return RenderResult(output_path)
        output_path.unlink(missing_ok=True)
        async with self._semaphore:
            if _valid_cached_png(output_path):
                os.utime(output_path, None)
                return RenderResult(output_path)
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(
                    self._render,
                    data,
                    poster_path,
                    output_path,
                    viewer_follows,
                )
                if not _valid_cached_png(output_path):
                    output_path.unlink(missing_ok=True)
                    return RenderResult(None, "invalid_rendered_png")
                return RenderResult(output_path)
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                output_path.unlink(missing_ok=True)
                logger.warning(
                    "anime_card.render_failed",
                    extra={
                        "anime_id": str(data.anime_id),
                        "error_type": type(exc).__name__,
                    },
                )
                return RenderResult(None, type(exc).__name__)

    def _validate_fonts(self) -> None:
        _load_font(self._cjk_font_path, 24)
        _load_font(self._mono_font_path, 24)

    def _render(
        self,
        data: AnimeCardData,
        poster_path: Path,
        output_path: Path,
        viewer_follows: bool,
    ) -> None:
        with Image.open(poster_path) as source:
            poster = source.convert("RGB")
        canvas = Image.new("RGB", CARD_SIZE, PAPER)
        canvas.paste(_poster_panel(poster), (0, 0))
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(self._cjk_font_path, 42)
        subtitle_font = _load_font(self._cjk_font_path, 23)
        body_font = _load_font(self._cjk_font_path, 25)
        small_font = _load_font(self._cjk_font_path, 20)
        time_font = _load_font(self._mono_font_path, 48)
        mono_small = _load_font(self._mono_font_path, 18)

        metadata = " / ".join(
            str(value)
            for value in (data.release_year, data.season_name, data.media_format)
            if value is not None
        )
        if metadata:
            draw.text((440, 38), metadata, fill=SIGNAL_BLUE, font=mono_small)
        _draw_wrapped(
            draw,
            data.display_title,
            xy=(440, 78),
            max_width=520,
            max_lines=2,
            fill=INK,
            font=title_font,
            line_gap=6,
        )
        title_height = 112
        if data.title_jp:
            _draw_wrapped(
                draw,
                data.title_jp,
                xy=(440, 78 + title_height),
                max_width=520,
                max_lines=1,
                fill=SIGNAL_BLUE,
                font=subtitle_font,
                line_gap=0,
            )

        track_y = 250
        draw.rounded_rectangle((440, track_y, 960, track_y + 126), radius=18, fill=MIST_BLUE)
        draw.rounded_rectangle((440, track_y, 625, track_y + 126), radius=18, fill=SIGNAL_BLUE)
        if data.next_airing and data.next_airing.air_at:
            local_at = data.next_airing.air_at.astimezone(ZoneInfo(data.timezone_name))
            time_label = local_at.strftime("%H:%M")
            date_label = local_at.strftime("%m-%d")
            weekday = "一二三四五六日"[local_at.weekday()]
        elif data.next_airing:
            time_label = "待定"
            date_label = data.next_airing.air_date.strftime("%m-%d")
            weekday = "一二三四五六日"[data.next_airing.air_date.weekday()]
        else:
            time_label = "待定"
            date_label = "暂无已知下一集"
            weekday = ""
        draw.text((461, track_y + 32), time_label, fill="white", font=time_font)
        draw.text((654, track_y + 28), date_label, fill=INK, font=body_font)
        if weekday:
            draw.text((654, track_y + 69), f"周{weekday}", fill=SIGNAL_BLUE, font=small_font)
        episode = data.next_airing.episode_label if data.next_airing else None
        if episode and episode != "?":
            episode = episode.lstrip("0") or "0"
            draw.text((820, track_y + 69), f"第 {episode} 集", fill=INK, font=small_font)

        stat_y = 412
        stats = []
        if data.bangumi_score is not None:
            stats.append(f"BGM {data.bangumi_score:g}")
        if data.total_episodes is not None:
            stats.append(f"全 {data.total_episodes} 集")
        if data.airing_status:
            stats.append(data.airing_status)
        if stats:
            draw.text((440, stat_y), "  ·  ".join(stats), fill=INK, font=body_font)
        chip_x = 440
        for source_name in data.sources:
            label = {
                "bangumi": "BANGUMI",
                "animeschedule": "ANIMESCHEDULE",
                "anilist": "ANILIST",
                "mikan": "MIKAN",
            }[source_name]
            box = draw.textbbox((0, 0), label, font=mono_small)
            width = box[2] - box[0] + 28
            draw.rounded_rectangle(
                (chip_x, 486, chip_x + width, 524),
                radius=12,
                fill=MIST_BLUE,
            )
            draw.text((chip_x + 14, 494), label, fill=SIGNAL_BLUE, font=mono_small)
            chip_x += width + 10
        draw.rounded_rectangle((876, 30, 960, 63), radius=10, fill=ON_AIR_RED)
        draw.text((890, 37), "ON AIR", fill="white", font=mono_small)
        if viewer_follows:
            _draw_following_seal(draw, x=768, y=30, font=small_font)
        draw.line((440, 558, 960, 558), fill=SIGNAL_BLUE, width=3)
        draw.text((440, 568), "ANIME BROADCAST SIGNAL", fill=SIGNAL_BLUE, font=mono_small)

        temp_path = output_path.parent / f".render-{secrets.token_hex(8)}.tmp"
        try:
            canvas.save(temp_path, format="PNG", optimize=True)
            os.replace(temp_path, output_path)
        finally:
            temp_path.unlink(missing_ok=True)


def _poster_panel(source: Image.Image) -> Image.Image:
    target_width, target_height = POSTER_SIZE
    background = source.copy()
    cover_scale = max(target_width / source.width, target_height / source.height)
    cover_size = (
        max(1, round(source.width * cover_scale)),
        max(1, round(source.height * cover_scale)),
    )
    background = background.resize(cover_size, Image.Resampling.LANCZOS)
    left = (background.width - target_width) // 2
    top = (background.height - target_height) // 2
    background = background.crop((left, top, left + target_width, top + target_height))
    background = background.filter(ImageFilter.GaussianBlur(radius=18))
    contain_scale = min(target_width / source.width, target_height / source.height)
    contain_size = (
        max(1, round(source.width * contain_scale)),
        max(1, round(source.height * contain_scale)),
    )
    foreground = source.resize(contain_size, Image.Resampling.LANCZOS)
    x = (target_width - foreground.width) // 2
    y = (target_height - foreground.height) // 2
    background.paste(foreground, (x, y))
    return background


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    xy: tuple[int, int],
    max_width: int,
    max_lines: int,
    fill: str,
    font: FreeTypeFont,
    line_gap: int,
) -> None:
    lines: list[str] = []
    current = ""
    for character in text.strip():
        candidate = current + character
        box = draw.textbbox((0, 0), candidate, font=font)
        if current and box[2] - box[0] > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last:
            candidate = last + "…"
            box = draw.textbbox((0, 0), candidate, font=font)
            if box[2] - box[0] <= max_width:
                lines[-1] = candidate
                break
            last = last[:-1]
    x, y = xy
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font)
        box = draw.textbbox((x, y), line, font=font)
        y = box[3] + line_gap


def _load_font(path: Path, size: int) -> FreeTypeFont:
    if not path.is_file():
        raise OSError(f"required font is missing: {path.name}")
    return ImageFont.truetype(str(path), size=size)


def _draw_following_seal(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    font: FreeTypeFont,
) -> None:
    draw.rounded_rectangle(
        (x, y, x + 94, y + 33),
        radius=10,
        fill=FOLLOW_GOLD,
        outline="#B98727",
        width=2,
    )
    draw.text((x + 13, y + 6), "追番中", fill=INK, font=font)


def _cache_fingerprint(
    data: AnimeCardData,
    viewer_follows: bool,
    viewer_scope: str | None,
) -> str:
    payload = {
        "layout": "card-subscription-v1",
        "projection": data.projection_fingerprint,
        "viewer_follows": viewer_follows,
        "viewer_scope": viewer_scope,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _valid_cached_png(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            return image.format == "PNG" and image.size == CARD_SIZE
    except (FileNotFoundError, OSError, UnidentifiedImageError):
        return False


__all__ = [
    "CARD_SIZE",
    "INK",
    "MIST_BLUE",
    "ON_AIR_RED",
    "PAPER",
    "POSTER_SIZE",
    "SIGNAL_BLUE",
    "AnimeCardRenderer",
    "RenderResult",
]
