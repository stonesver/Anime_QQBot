from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from PIL.ImageFont import FreeTypeFont

from anime_qqbot.presentation.renderer import RenderResult

logger = logging.getLogger(__name__)

WEEKLY_WIDTH = 1680
WEEKLY_MAX_HEIGHT = 3600
DAILY_WIDTH = 1080
DAILY_MAX_HEIGHT = 3000
PANEL = "#1D3939"
PANEL_ALT = "#234444"
TEXT = "#F4FBF3"
MUTED = "#B8D3C9"
GOLD = "#E6B65B"
MINT = "#A3D5BF"
PINK = "#D97597"
LINE = "#3B5A5A"
RENDER_VERSION = "calendar-v2"


class ScheduleImageRenderer:
    """Render cached weekly-calendar and daily-schedule PNGs locally."""

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

    async def render_weekly_cached(
        self,
        rows: Sequence[Any],
        *,
        timezone: ZoneInfo,
        week_start: date,
        week_end: date,
    ) -> RenderResult:
        return await self._render_cached(
            kind="weekly",
            rows=rows,
            timezone=timezone,
            range_start=week_start,
            range_end=week_end,
            draw=lambda materialized, output_path: self._render_weekly(
                materialized,
                timezone=timezone,
                week_start=week_start,
                week_end=week_end,
                output_path=output_path,
            ),
        )

    async def render_daily_cached(
        self,
        rows: Sequence[Any],
        *,
        timezone: ZoneInfo,
        target_date: date,
    ) -> RenderResult:
        return await self._render_cached(
            kind="daily",
            rows=rows,
            timezone=timezone,
            range_start=target_date,
            range_end=target_date,
            draw=lambda materialized, output_path: self._render_daily(
                materialized,
                timezone=timezone,
                target_date=target_date,
                output_path=output_path,
            ),
        )

    async def _render_cached(
        self,
        *,
        kind: str,
        rows: Sequence[Any],
        timezone: ZoneInfo,
        range_start: date,
        range_end: date,
        draw: Callable[[tuple[Any, ...], Path], None],
    ) -> RenderResult:
        materialized = tuple(rows)
        if not materialized:
            return RenderResult(None, "empty_schedule")
        fingerprint = _fingerprint(
            materialized,
            kind=kind,
            timezone=timezone,
            range_start=range_start,
            range_end=range_end,
        )
        output_path = self._render_root / kind / f"{fingerprint}.png"
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
                await asyncio.to_thread(draw, materialized, output_path)
                if not _valid_cached_png(output_path):
                    output_path.unlink(missing_ok=True)
                    return RenderResult(None, "invalid_rendered_png")
                return RenderResult(output_path)
            except (OSError, ValueError, UnidentifiedImageError) as exc:
                output_path.unlink(missing_ok=True)
                logger.warning(
                    "schedule_image.render_failed",
                    extra={"schedule_kind": kind, "error_type": type(exc).__name__},
                )
                return RenderResult(None, type(exc).__name__)

    def _render_weekly(
        self,
        rows: Sequence[Any],
        *,
        timezone: ZoneInfo,
        week_start: date,
        week_end: date,
        output_path: Path,
    ) -> None:
        days = tuple(week_start + timedelta(days=offset) for offset in range(7))
        if days[-1] != week_end:
            raise ValueError("weekly schedule must span seven days")
        grouped: dict[date, list[Any]] = defaultdict(list)
        for row in rows:
            air_date = getattr(row, "air_date", None)
            if air_date in days:
                grouped[air_date].append(row)
        for day_rows in grouped.values():
            day_rows.sort(key=lambda row: _row_sort_key(row, timezone))

        max_items = max(len(grouped[day]) for day in days)
        compact = max_items > 9
        card_height = 72 if compact else 88
        header_height = 270
        day_heading_height = 66
        footer_height = 80
        body_height = 18 + max_items * (card_height + 10)
        canvas_height = header_height + day_heading_height + body_height + footer_height
        if canvas_height > WEEKLY_MAX_HEIGHT:
            raise ValueError("weekly_schedule_too_dense")

        canvas = Image.new("RGB", (WEEKLY_WIDTH, canvas_height), PANEL)
        draw = ImageDraw.Draw(canvas)
        _draw_background(draw, WEEKLY_WIDTH, canvas_height)
        title_font = _load_font(self._cjk_font_path, 62)
        label_font = _load_font(self._mono_font_path, 20)
        subtitle_font = _load_font(self._cjk_font_path, 24)
        day_font = _load_font(self._cjk_font_path, 24)
        date_font = _load_font(self._mono_font_path, 17)
        time_font = _load_font(self._mono_font_path, 18 if compact else 20)
        pending_time_font = _load_font(self._cjk_font_path, 17 if compact else 19)
        body_font = _load_font(self._cjk_font_path, 17 if compact else 19)
        chip_font = _load_font(self._mono_font_path, 14)
        footer_font = _load_font(self._cjk_font_path, 18)

        draw.text((72, 48), "SEASONAL CALENDAR", fill=MUTED, font=label_font)
        draw.text((72, 82), "本周放送", fill=TEXT, font=title_font)
        draw.text(
            (76, 168),
            f"{week_start:%m/%d} — {week_end:%m/%d} · {timezone.key}",
            fill=MUTED,
            font=subtitle_font,
        )
        badge = f"WEEK {week_start.isocalendar().week:02d}"
        _draw_badge(draw, (1410, 58), badge, label_font)

        left = 72
        right = WEEKLY_WIDTH - 72
        gap = 12
        column_width = (right - left - gap * 6) // 7
        content_top = header_height
        for index, day in enumerate(days):
            x = left + index * (column_width + gap)
            is_today = False
            _draw_weekly_day(
                draw,
                day=day,
                rows=grouped[day],
                timezone=timezone,
                x=x,
                y=content_top,
                width=column_width,
                card_height=card_height,
                is_today=is_today,
                day_font=day_font,
                date_font=date_font,
                time_font=time_font,
                pending_time_font=pending_time_font,
                body_font=body_font,
                chip_font=chip_font,
            )

        footer_y = canvas_height - footer_height + 20
        draw.text(
            (72, footer_y),
            f"共 {len(rows)} 部 · 数据按群时区计算 · 待定节目排在当天末尾",
            fill=MUTED,
            font=footer_font,
        )
        draw.text(
            (72, footer_y + 30),
            "发送「番剧 今天」查看当天完整放送表",
            fill="#8FB5A7",
            font=footer_font,
        )
        _save_png(canvas, output_path)

    def _render_daily(
        self,
        rows: Sequence[Any],
        *,
        timezone: ZoneInfo,
        target_date: date,
        output_path: Path,
    ) -> None:
        ordered = sorted(rows, key=lambda row: _row_sort_key(row, timezone))
        known_rows = [row for row in ordered if getattr(row, "air_at", None) is not None]
        pending_rows = [row for row in ordered if getattr(row, "air_at", None) is None]
        header_height = 270
        section_height = 44
        row_height = 68
        footer_height = 72
        canvas_height = (
            header_height
            + section_height
            + len(known_rows) * row_height
            + (section_height + len(pending_rows) * row_height if pending_rows else 0)
            + footer_height
        )
        canvas_height = max(canvas_height, 540)
        if canvas_height > DAILY_MAX_HEIGHT:
            raise ValueError("daily_schedule_too_dense")

        canvas = Image.new("RGB", (DAILY_WIDTH, canvas_height), PANEL)
        draw = ImageDraw.Draw(canvas)
        _draw_background(draw, DAILY_WIDTH, canvas_height)
        title_font = _load_font(self._cjk_font_path, 62)
        label_font = _load_font(self._mono_font_path, 20)
        day_badge_font = _load_font(self._cjk_font_path, 20)
        subtitle_font = _load_font(self._cjk_font_path, 23)
        section_font = _load_font(self._cjk_font_path, 19)
        time_font = _load_font(self._mono_font_path, 23)
        pending_time_font = _load_font(self._cjk_font_path, 21)
        body_font = _load_font(self._cjk_font_path, 23)
        chip_font = _load_font(self._mono_font_path, 16)
        footer_font = _load_font(self._cjk_font_path, 18)

        draw.text((72, 48), "DAILY BROADCAST", fill=MUTED, font=label_font)
        draw.text((72, 82), "今天放送", fill=TEXT, font=title_font)
        weekday = _weekday_label(target_date)
        draw.text(
            (76, 168),
            f"{target_date:%Y 年 %m 月 %d 日} · {weekday} · {timezone.key}",
            fill=MUTED,
            font=subtitle_font,
        )
        _draw_badge(draw, (860, 58), weekday, day_badge_font)

        y = header_height
        y = _draw_daily_section(
            draw,
            y=y,
            label=f"已知时间 · {len(known_rows)} 部",
            color=GOLD,
            font=section_font,
        )
        for row in known_rows:
            _draw_daily_row(
                draw,
                row=row,
                timezone=timezone,
                y=y,
                accent=GOLD,
                time_font=time_font,
                pending_time_font=pending_time_font,
                body_font=body_font,
                chip_font=chip_font,
            )
            y += row_height
        if pending_rows:
            y = _draw_daily_section(
                draw,
                y=y,
                label=f"播出时间待定 · {len(pending_rows)} 部",
                color=MINT,
                font=section_font,
            )
            for row in pending_rows:
                _draw_daily_row(
                    draw,
                    row=row,
                    timezone=timezone,
                    y=y,
                    accent=MINT,
                    time_font=time_font,
                    pending_time_font=pending_time_font,
                    body_font=body_font,
                    chip_font=chip_font,
                )
                y += row_height
        draw.text(
            (72, canvas_height - footer_height + 20),
            f"共 {len(rows)} 部 · 数据按群时区计算",
            fill=MUTED,
            font=footer_font,
        )
        _save_png(canvas, output_path)


def _draw_weekly_day(
    draw: ImageDraw.ImageDraw,
    *,
    day: date,
    rows: Sequence[Any],
    timezone: ZoneInfo,
    x: int,
    y: int,
    width: int,
    card_height: int,
    is_today: bool,
    day_font: FreeTypeFont,
    date_font: FreeTypeFont,
    time_font: FreeTypeFont,
    pending_time_font: FreeTypeFont,
    body_font: FreeTypeFont,
    chip_font: FreeTypeFont,
) -> None:
    border = GOLD if is_today else LINE
    draw.rounded_rectangle(
        (x, y, x + width, y + 64),
        radius=13,
        fill="#214844",
        outline=border,
        width=2,
    )
    draw.text((x + 14, y + 11), _weekday_label(day), fill=TEXT, font=day_font)
    draw.text((x + 14, y + 38), f"{day:%m/%d}", fill=MUTED, font=date_font)
    card_y = y + 76
    for row in rows:
        _draw_weekly_card(
            draw,
            row=row,
            timezone=timezone,
            x=x,
            y=card_y,
            width=width,
            height=card_height,
            time_font=time_font,
            pending_time_font=pending_time_font,
            body_font=body_font,
            chip_font=chip_font,
        )
        card_y += card_height + 10


def _draw_weekly_card(
    draw: ImageDraw.ImageDraw,
    *,
    row: Any,
    timezone: ZoneInfo,
    x: int,
    y: int,
    width: int,
    height: int,
    time_font: FreeTypeFont,
    pending_time_font: FreeTypeFont,
    body_font: FreeTypeFont,
    chip_font: FreeTypeFont,
) -> None:
    air_at = getattr(row, "air_at", None)
    accent = GOLD if air_at is not None else MINT
    time_label = air_at.astimezone(timezone).strftime("%H:%M") if air_at else "待定"
    title = str(getattr(row, "display_title", None) or getattr(row, "id", "未命名番剧"))
    episode_label = _episode_label(row)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=10, fill=PANEL_ALT)
    draw.text(
        (x + 11, y + 9),
        time_label,
        fill=accent,
        font=time_font if air_at is not None else pending_time_font,
    )
    chip_width = _chip_width(draw, episode_label, chip_font)
    chip_left = x + width - chip_width - 10
    _draw_chip(draw, chip_left, y + 8, episode_label, accent, chip_font)
    title = _fit_text(draw, title, font=body_font, max_width=width - 22)
    draw.text((x + 11, y + 38), title, fill=TEXT, font=body_font)


def _draw_daily_section(
    draw: ImageDraw.ImageDraw,
    *,
    y: int,
    label: str,
    color: str,
    font: FreeTypeFont,
) -> int:
    draw.line((72, y + 5, DAILY_WIDTH - 72, y + 5), fill=LINE, width=2)
    draw.text((72, y + 15), label, fill=color, font=font)
    return y + 44


def _draw_daily_row(
    draw: ImageDraw.ImageDraw,
    *,
    row: Any,
    timezone: ZoneInfo,
    y: int,
    accent: str,
    time_font: FreeTypeFont,
    pending_time_font: FreeTypeFont,
    body_font: FreeTypeFont,
    chip_font: FreeTypeFont,
) -> None:
    air_at = getattr(row, "air_at", None)
    time_label = air_at.astimezone(timezone).strftime("%H:%M") if air_at else "待定"
    title = str(getattr(row, "display_title", None) or getattr(row, "id", "未命名番剧"))
    episode_label = _episode_label(row)
    draw.line((72, y + 62, DAILY_WIDTH - 72, y + 62), fill=LINE, width=1)
    draw.text(
        (78, y + 19),
        time_label,
        fill=accent,
        font=time_font if air_at is not None else pending_time_font,
    )
    chip_width = _chip_width(draw, episode_label, chip_font)
    chip_left = DAILY_WIDTH - 78 - chip_width
    title = _fit_text(draw, title, font=body_font, max_width=chip_left - 178)
    draw.text((178, y + 19), title, fill=TEXT, font=body_font)
    _draw_chip(draw, chip_left, y + 15, episode_label, accent, chip_font)


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    label: str,
    font: FreeTypeFont,
) -> None:
    x, y = origin
    bounds = draw.textbbox((0, 0), label, font=font)
    width = bounds[2] - bounds[0] + 28
    draw.rounded_rectangle((x, y, x + width, y + 45), radius=18, fill=GOLD)
    draw.text((x + 14, y + 12), label, fill=PANEL, font=font)


def _draw_chip(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    accent: str,
    font: FreeTypeFont,
) -> None:
    width = _chip_width(draw, label, font)
    draw.rounded_rectangle((x, y, x + width, y + 30), radius=10, fill=accent)
    draw.text((x + 10, y + 8), label, fill=PANEL, font=font)


def _chip_width(draw: ImageDraw.ImageDraw, label: str, font: FreeTypeFont) -> int:
    bounds = draw.textbbox((0, 0), label, font=font)
    return bounds[2] - bounds[0] + 20


def _draw_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    draw.rectangle((0, 0, width, height), fill=PANEL)
    draw.rectangle((0, 0, width, 240), fill="#1B3838")
    draw.ellipse((-140, -150, 290, 220), fill="#2B5550")
    draw.ellipse((width - 280, -130, width + 110, 190), fill="#263D50")


def _row_sort_key(row: Any, timezone: ZoneInfo) -> tuple[bool, str, str]:
    air_at = getattr(row, "air_at", None)
    title = str(getattr(row, "display_title", None) or getattr(row, "id", ""))
    return (air_at is None, air_at.astimezone(timezone).isoformat() if air_at else "", title)


def _weekday_label(value: date) -> str:
    return f"周{'日一二三四五六'[(value.weekday() + 1) % 7]}"


def _episode_label(row: Any) -> str:
    episode = getattr(row, "episode_label", None)
    return f"EP {episode.lstrip('0') or '0'}" if episode and episode != "?" else "EP ??"


def _fit_text(draw: ImageDraw.ImageDraw, text: str, *, font: FreeTypeFont, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "…"
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return text + suffix if text else suffix


def _fingerprint(
    rows: Sequence[Any],
    *,
    kind: str,
    timezone: ZoneInfo,
    range_start: date,
    range_end: date,
) -> str:
    payload = {
        "layout": RENDER_VERSION,
        "kind": kind,
        "timezone": timezone.key,
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
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


def _save_png(canvas: Image.Image, output_path: Path) -> None:
    temp_path = output_path.parent / f".render-{secrets.token_hex(8)}.tmp"
    try:
        canvas.save(temp_path, format="PNG", optimize=True)
        os.replace(temp_path, output_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _valid_cached_png(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 128:
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError):
        return False


__all__ = [
    "DAILY_MAX_HEIGHT",
    "DAILY_WIDTH",
    "WEEKLY_MAX_HEIGHT",
    "WEEKLY_WIDTH",
    "ScheduleImageRenderer",
]
