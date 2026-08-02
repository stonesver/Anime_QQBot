from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from PIL.ImageFont import FreeTypeFont

from anime_qqbot.presentation.renderer import RenderResult

logger = logging.getLogger(__name__)

WEEKLY_WIDTH = 1200
WEEKLY_MAX_HEIGHT = 3600
PANEL = "#1D3939"
PANEL_ALT = "#234444"
TEXT = "#F4FBF3"
MUTED = "#B8D3C9"
GOLD = "#E6B65B"
MINT = "#A3D5BF"
PINK = "#D97597"
LINE = "#3B5A5A"
ACCENTS = (GOLD, MINT, PINK)


class WeeklyScheduleRenderer:
    """Render a complete weekly airing listing into one local PNG."""

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
        _load_font(cjk_font_path, 24)
        _load_font(mono_font_path, 24)

    async def render_cached(
        self,
        rows: Sequence[Any],
        *,
        timezone: ZoneInfo,
        week_start: date,
        week_end: date,
    ) -> RenderResult:
        materialized = tuple(rows)
        if not materialized:
            return RenderResult(None, "empty_schedule")
        fingerprint = _fingerprint(
            materialized,
            timezone=timezone,
            week_start=week_start,
            week_end=week_end,
        )
        output_path = self._render_root / f"{fingerprint}.png"
        if _valid_cached_png(output_path):
            os.utime(output_path, None)
            return RenderResult(output_path)
        output_path.unlink(missing_ok=True)
        async with self._semaphore:
            if _valid_cached_png(output_path):
                os.utime(output_path, None)
                return RenderResult(output_path)
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(
                    self._render,
                    materialized,
                    timezone,
                    week_start,
                    week_end,
                    output_path,
                )
                if not _valid_cached_png(output_path):
                    output_path.unlink(missing_ok=True)
                    return RenderResult(None, "invalid_rendered_png")
                return RenderResult(output_path)
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                output_path.unlink(missing_ok=True)
                logger.warning(
                    "weekly_schedule.render_failed",
                    extra={"error_type": type(exc).__name__},
                )
                return RenderResult(None, type(exc).__name__)

    def _render(
        self,
        rows: Sequence[Any],
        timezone: ZoneInfo,
        week_start: date,
        week_end: date,
        output_path: Path,
    ) -> None:
        grouped: dict[date | None, list[Any]] = defaultdict(list)
        for row in rows:
            grouped[getattr(row, "air_date", None)].append(row)
        days = sorted(grouped, key=lambda value: (value is None, value or date.max))
        group_count = len(days)
        row_count = len(rows)
        compact = row_count > 18
        group_gap = 54 if compact else 64
        row_height = 55 if compact else 68
        header_height = 270
        footer_height = 90
        canvas_height = min(
            WEEKLY_MAX_HEIGHT,
            max(
                720,
                header_height
                + footer_height
                + group_count * group_gap
                + row_count * row_height,
            ),
        )
        canvas = Image.new("RGB", (WEEKLY_WIDTH, canvas_height), PANEL)
        draw = ImageDraw.Draw(canvas)
        _draw_background(draw, canvas_height)
        title_font = _load_font(self._cjk_font_path, 58 if compact else 64)
        label_font = _load_font(self._mono_font_path, 20)
        subtitle_font = _load_font(self._cjk_font_path, 23)
        group_font = _load_font(self._cjk_font_path, 25 if compact else 28)
        time_font = _load_font(self._mono_font_path, 28 if compact else 32)
        pending_time_font = _load_font(self._cjk_font_path, 25 if compact else 28)
        body_font = _load_font(self._cjk_font_path, 25 if compact else 28)
        chip_font = _load_font(self._mono_font_path, 18 if compact else 20)
        footer_font = _load_font(self._cjk_font_path, 18)

        draw.text((72, 54), "SEASONAL BROADCAST", fill=MUTED, font=label_font)
        draw.text((72, 88), "本周放送_", fill=TEXT, font=title_font)
        draw.text(
            (76, 170),
            f"{week_start:%m/%d} — {week_end:%m/%d} · {timezone.key}",
            fill=MUTED,
            font=subtitle_font,
        )
        draw.rounded_rectangle((962, 56, 1128, 108), radius=22, fill=GOLD)
        draw.text(
            (995, 70),
            f"WEEK {week_start.isocalendar().week:02d}",
            fill=PANEL,
            font=label_font,
        )
        draw.ellipse((1005, 140, 1150, 285), fill="#2A5150", outline="#4B7770", width=3)
        draw.arc((1025, 160, 1130, 265), start=35, end=310, fill=PINK, width=4)
        draw.ellipse((1060, 195, 1075, 210), fill=MINT)
        draw.ellipse((1105, 230, 1118, 243), fill=GOLD)

        y = header_height
        for index, day in enumerate(days):
            accent = ACCENTS[index % len(ACCENTS)]
            if day is None:
                day_label = "日期待定"
            else:
                weekday = "一二三四五六日"[day.weekday()]
                day_label = f"周{weekday} · {day:%m-%d}"
            draw.ellipse((72, y + 9, 86, y + 23), fill=accent)
            draw.text((104, y), day_label, fill=accent, font=group_font)
            y += group_gap
            for row in grouped[day]:
                _draw_row(
                    draw,
                    row,
                    timezone=timezone,
                    y=y,
                    time_font=time_font,
                    pending_time_font=pending_time_font,
                    body_font=body_font,
                    chip_font=chip_font,
                    accent=accent,
                    compact=compact,
                )
                y += row_height
            draw.line((72, y - 10, 1128, y - 10), fill=LINE, width=2)

        footer_y = canvas_height - footer_height + 22
        draw.text(
            (72, footer_y),
            f"共 {row_count} 部 · 数据按群时区计算",
            fill=MUTED,
            font=footer_font,
        )
        draw.text(
            (72, footer_y + 31),
            "发送「番剧 详情」查看单部番剧信息",
            fill="#8FB5A7",
            font=footer_font,
        )
        _draw_sparkle(draw, center=(1072, footer_y + 31), color=PINK)

        temp_path = output_path.parent / f".render-{secrets.token_hex(8)}.tmp"
        try:
            canvas.save(temp_path, format="PNG", optimize=True)
            os.replace(temp_path, output_path)
        finally:
            temp_path.unlink(missing_ok=True)


def _draw_background(draw: ImageDraw.ImageDraw, height: int) -> None:
    draw.rectangle((0, 0, WEEKLY_WIDTH, height), fill=PANEL)
    draw.rectangle((0, 0, WEEKLY_WIDTH, 250), fill="#1B3838")
    draw.ellipse((-120, -160, 260, 220), fill="#2B5550")
    draw.ellipse((945, -125, 1270, 200), fill="#263D50")
    draw.rectangle((0, 250, WEEKLY_WIDTH, height), fill=PANEL)


def _draw_row(
    draw: ImageDraw.ImageDraw,
    row: Any,
    *,
    timezone: ZoneInfo,
    y: int,
    time_font: FreeTypeFont,
    pending_time_font: FreeTypeFont,
    body_font: FreeTypeFont,
    chip_font: FreeTypeFont,
    accent: str,
    compact: bool,
) -> None:
    air_at = getattr(row, "air_at", None)
    time_label = air_at.astimezone(timezone).strftime("%H:%M") if air_at else "待定"
    title = str(getattr(row, "display_title", None) or getattr(row, "id", "未命名番剧"))
    episode = getattr(row, "episode_label", None)
    episode_label = f"EP {episode.lstrip('0') or '0'}" if episode and episode != "?" else "EP ??"
    chip_box = draw.textbbox((0, 0), episode_label, font=chip_font)
    chip_width = chip_box[2] - chip_box[0] + 30
    chip_left = 1128 - chip_width
    title_left = 254
    title_right = chip_left - 26
    title = _fit_text(draw, title, font=body_font, max_width=title_right - title_left)
    draw.text(
        (78, y + 8),
        time_label,
        fill=accent,
        font=pending_time_font if air_at is None else time_font,
    )
    draw.text((title_left, y + 8), title, fill=TEXT, font=body_font)
    chip_fill = {GOLD: GOLD, MINT: MINT, PINK: PINK}[accent]
    chip_text = PANEL if accent != PINK else "#3E2635"
    draw.rounded_rectangle((chip_left, y + 5, 1128, y + 48), radius=15, fill=chip_fill)
    draw.text((chip_left + 15, y + 14), episode_label, fill=chip_text, font=chip_font)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, *, font: FreeTypeFont, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "…"
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return text + suffix if text else suffix


def _draw_sparkle(draw: ImageDraw.ImageDraw, *, center: tuple[int, int], color: str) -> None:
    x, y = center
    draw.polygon(
        [
            (x, y - 13),
            (x + 4, y - 4),
            (x + 13, y),
            (x + 4, y + 4),
            (x, y + 13),
            (x - 4, y + 4),
            (x - 13, y),
            (x - 4, y - 4),
        ],
        fill=color,
    )


def _fingerprint(
    rows: Sequence[Any],
    *,
    timezone: ZoneInfo,
    week_start: date,
    week_end: date,
) -> str:
    payload = {
        "timezone": timezone.key,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "rows": [_row_fingerprint(row) for row in rows],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _row_fingerprint(row: Any) -> dict[str, object]:
    air_date = getattr(row, "air_date", None)
    air_at = getattr(row, "air_at", None)
    return {
        "id": str(getattr(row, "id", "")),
        "title": getattr(row, "display_title", None),
        "date": air_date.isoformat() if air_date is not None else None,
        "at": air_at.isoformat() if air_at is not None else None,
        "episode": getattr(row, "episode_label", None),
    }


def _load_font(path: Path, size: int) -> FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)


def _valid_cached_png(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 128:
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError):
        return False


__all__ = ["WEEKLY_MAX_HEIGHT", "WEEKLY_WIDTH", "WeeklyScheduleRenderer"]
