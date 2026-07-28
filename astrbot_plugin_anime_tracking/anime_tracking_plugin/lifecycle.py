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
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from anime_qqbot.notifications.governor import GovernorLimits, SendGovernor
from anime_qqbot.persistence.session import create_engine, create_session_factory

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
            if self._start_dispatcher_enabled:
                await self._start_dispatcher()
        except Exception:
            self._running = False
            await self._engine.dispose()
            self._engine = None
            self.sessions = None
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

    async def shutdown(self) -> None:
        if not self._running:
            return
        self._running = False
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
