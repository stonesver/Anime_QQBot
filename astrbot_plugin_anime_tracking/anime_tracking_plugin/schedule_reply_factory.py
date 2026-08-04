from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from anime_qqbot.application.context import ChatContext
from anime_qqbot.presentation.schedule_renderer import ScheduleImageRenderer
from anime_qqbot.presentation.subscription_presentation import SubscriptionPresentationReader

from .adapter import Reply

logger = logging.getLogger(__name__)


class ScheduleReplyFactory:
    """Build one-image replies for schedule listings with text fallback."""

    def __init__(
        self,
        *,
        renderer: ScheduleImageRenderer,
        subscription_reader: SubscriptionPresentationReader,
    ) -> None:
        self._renderer = renderer
        self._subscription_reader = subscription_reader

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
            rendered_rows, cache_scope = await self._with_group_heat(rows, ctx)
            rendered = await self._renderer.render_weekly_cached(
                rendered_rows,
                timezone=ctx.timezone,
                week_start=week_start,
                week_end=week_end,
                cache_scope=cache_scope,
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
            rendered_rows, cache_scope = await self._with_group_heat(rows, ctx)
            rendered = await self._renderer.render_daily_cached(
                rendered_rows,
                timezone=ctx.timezone,
                target_date=target_date,
                cache_scope=cache_scope,
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

    async def _with_group_heat(
        self,
        rows: Sequence[Any],
        ctx: ChatContext,
    ) -> tuple[tuple[Any, ...], str | None]:
        try:
            subscriptions = await self._subscription_reader.read(
                ctx=ctx,
                anime_ids=tuple(row.id for row in rows),
                include_viewer_state=False,
            )
        except Exception as exc:
            logger.warning(
                "schedule_reply_factory.subscription_presentation_unavailable",
                extra={"error_type": type(exc).__name__},
            )
            return tuple(rows), None
        return (
            tuple(
                SimpleNamespace(
                    **vars(row),
                    group_follow_count=subscriptions.group_follow_counts.get(row.id, 0),
                )
                for row in rows
            ),
            subscriptions.group_scope,
        )


__all__ = ["ScheduleReplyFactory"]
