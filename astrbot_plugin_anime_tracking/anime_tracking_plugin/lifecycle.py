"""Plugin lifecycle: database sessions, outbox consumer, graceful shutdown.

The lifecycle owns:

* the SQLAlchemy async session factory (built once from ``DATABASE_URL``),
* the EventAdapter used by command handlers,
* the OutboxDispatcher consumer loop that claims NotificationJob rows
  and pushes them back through the AstrBot context.

``start()`` is idempotent: a second call while the plugin is already
running is a no-op. ``shutdown()`` cancels every background task and
disposes the engine; it is safe to call when the plugin never started.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from anime_qqbot.notifications.governor import GovernorLimits, SendGovernor
from anime_qqbot.operations.napcat_status import (
    NapCatOneBotClient,
    NapCatStatusMonitor,
)
from anime_qqbot.operations.runtime_status_repository import (
    RuntimeComponentStatusRepository,
)
from anime_qqbot.persistence.session import create_engine, create_session_factory
from anime_qqbot.presentation.assembler import CardDataAssembler
from anime_qqbot.presentation.poster_cache import PosterCache
from anime_qqbot.presentation.renderer import AnimeCardRenderer
from anime_qqbot.presentation.schedule_renderer import ScheduleImageRenderer

logger = logging.getLogger(__name__)


class PluginLifecycle:
    """Manages start / stop for the anime_tracking plugin.

    The instance is stored on the Context for access by commands and the
    outbox dispatcher. In production `Context` is the AstrBot context; in
    tests a fake context with the same interface can be used.
    """

    def __init__(
        self,
        context: Any = None,
        *,
        config: dict[str, Any] | None = None,
        start_dispatcher: bool = True,
    ) -> None:
        self._context = context
        self.config = config or {}
        self._start_dispatcher_enabled = start_dispatcher
        self._running = False
        self._tasks: list[asyncio.Task[object]] = []
        self._engine: AsyncEngine | None = None
        self.sessions: async_sessionmaker[AsyncSession] | None = None
        self.dispatcher: Any | None = None
        self.napcat_monitor: NapCatStatusMonitor | None = None
        self.card_reply_factory: Any | None = None
        self.schedule_reply_factory: Any | None = None
        self._local_poster_cache: PosterCache | None = None
        self.governor = SendGovernor(limits=self._governor_limits())

    @classmethod
    def from_context(cls, context: Any) -> PluginLifecycle:
        key = "__anime_tracking_lifecycle__"
        obj = getattr(context, key, None)
        if obj is None:
            obj = cls(context)
            setattr(context, key, obj)
        return cast(PluginLifecycle, obj)

    async def start(self) -> None:
        if self._running:
            return
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for the anime_tracking plugin")
        self._engine = create_engine(database_url)
        self.sessions = create_session_factory(self._engine)
        self._running = True
        try:
            self._start_card_presentation()
            self._start_napcat_monitor()
            if self._start_dispatcher_enabled:
                await self._start_dispatcher()
        except Exception:
            self._running = False
            if self.napcat_monitor is not None:
                await self.napcat_monitor.stop()
            for task in self._tasks:
                task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
                self._tasks.clear()
            await self._engine.dispose()
            self._engine = None
            self.sessions = None
            self.dispatcher = None
            self.card_reply_factory = None
            self.schedule_reply_factory = None
            self._local_poster_cache = None
            self.napcat_monitor = None
            raise
        logger.info("anime_tracking plugin started")

    async def _start_dispatcher(self) -> None:
        from .dispatcher import OutboxDispatcher

        if self.sessions is None:
            return
        self.dispatcher = OutboxDispatcher(lifecycle=self)
        task = asyncio.create_task(self.dispatcher.run())
        self.dispatcher.task = task
        self._tasks.append(task)

    def _start_napcat_monitor(self) -> None:
        if self.sessions is None:
            return
        base_url = os.environ.get("NAPCAT_ONEBOT_URL")
        token = os.environ.get("ONEBOT_TOKEN")
        if not base_url or not token:
            logger.info("napcat_status.monitor_disabled")
            return
        self.napcat_monitor = NapCatStatusMonitor(
            client=NapCatOneBotClient(base_url=base_url, token=token),
            repository=RuntimeComponentStatusRepository(self.sessions),
            interval_seconds=float(os.environ.get("NAPCAT_STATUS_POLL_SECONDS", "60")),
        )
        self._tasks.append(asyncio.create_task(self.napcat_monitor.run()))

    def _start_card_presentation(self) -> None:
        if not bool(self.config.get("card_presentation_enabled", True)):
            return
        if self.sessions is None:
            return
        cjk_font = Path(
            os.environ.get(
                "ANIME_CARD_CJK_FONT",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            )
        )
        mono_font = Path(
            os.environ.get(
                "ANIME_CARD_MONO_FONT",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            )
        )
        if not cjk_font.is_file() or not mono_font.is_file():
            logger.warning(
                "anime_tracking.card_fonts_unavailable",
                extra={"card_presentation_enabled": False},
            )
            return
        asset_root = Path(os.environ.get("CARD_ASSET_ROOT", "/var/lib/anime-qqbot/cards"))
        self._local_poster_cache = PosterCache(asset_root)
        renderer = AnimeCardRenderer(
            asset_root / "renders",
            cjk_font_path=cjk_font,
            mono_font_path=mono_font,
        )
        schedule_renderer = ScheduleImageRenderer(
            asset_root / "schedules",
            cjk_font_path=cjk_font,
            mono_font_path=mono_font,
        )
        from .card_reply_factory import CardReplyFactory
        from .schedule_reply_factory import ScheduleReplyFactory

        self.card_reply_factory = CardReplyFactory(
            assembler=CardDataAssembler(self.sessions),
            poster_locator=self._local_poster_cache.find_local_poster,
            renderer=renderer,
        )
        self.schedule_reply_factory = ScheduleReplyFactory(renderer=schedule_renderer)

    async def shutdown(self) -> None:
        if not self._running:
            return
        self._running = False
        if self.napcat_monitor is not None:
            await self.napcat_monitor.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        if self.dispatcher is not None:
            await self.dispatcher.stop()
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        self.sessions = None
        self.dispatcher = None
        self.napcat_monitor = None
        self.card_reply_factory = None
        self.schedule_reply_factory = None
        self._local_poster_cache = None
        logger.info("anime_tracking plugin shut down")

    @property
    def running(self) -> bool:
        return self._running

    def _governor_limits(self) -> GovernorLimits:
        def number(name: str, default: float) -> float:
            return float(self.config.get(name, default))

        def integer(name: str, default: int) -> int:
            return int(self.config.get(name, default))

        return GovernorLimits(
            global_interval_seconds=number("send_global_interval_seconds", 2.5),
            global_burst=integer("send_global_burst", 2),
            group_interval_seconds=number("send_group_interval_seconds", 5),
            user_interval_seconds=number("send_user_interval_seconds", 5),
            user_limit_per_minute=integer("send_user_limit_per_minute", 10),
            proactive_group_interval_seconds=number("send_proactive_group_interval_seconds", 60),
            proactive_group_limit_per_10_minutes=integer(
                "send_proactive_group_limit_per_10_minutes", 3
            ),
        )


__all__ = ["PluginLifecycle"]
