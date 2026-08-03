from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from anime_qqbot.application.context import ChatContext
from anime_qqbot.presentation.schedule_renderer import ScheduleImageRenderer

from .adapter import Reply

logger = logging.getLogger(__name__)


class ScheduleReplyFactory:
    """Build one-image replies for schedule listings with text fallback."""

    def __init__(self, *, renderer: ScheduleImageRenderer) -> None:
        self._renderer = renderer

    async def build_weekly(
        self,
        *,
        rows: Sequence[Any],
        ctx: ChatContext,
        fallback: Reply,
        now: datetime,
    ) -> Reply:
        if not rows:
            return fallback
        local_today = now.astimezone(ctx.timezone).date()
        week_start = local_today - timedelta(days=(local_today.weekday() + 1) % 7)
        week_end = week_start + timedelta(days=6)
        try:
            rendered = await self._renderer.render_weekly_cached(
                rows,
                timezone=ctx.timezone,
                week_start=week_start,
                week_end=week_end,
            )
            if not rendered.succeeded or rendered.path is None:
                return fallback
            return Reply.from_image(rendered.path)
        except Exception as exc:
            logger.warning(
                "weekly_schedule_reply.fallback",
                extra={"error_type": type(exc).__name__},
            )
            return fallback

    async def build_today(
        self,
        *,
        rows: Sequence[Any],
        ctx: ChatContext,
        fallback: Reply,
        target_date: date,
    ) -> Reply:
        if not rows:
            return fallback
        try:
            rendered = await self._renderer.render_daily_cached(
                rows,
                timezone=ctx.timezone,
                target_date=target_date,
            )
            if not rendered.succeeded or rendered.path is None:
                return fallback
            return Reply.from_image(rendered.path)
        except Exception as exc:
            logger.warning(
                "daily_schedule_reply.fallback",
                extra={"error_type": type(exc).__name__},
            )
            return fallback


__all__ = ["ScheduleReplyFactory"]
