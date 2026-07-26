"""Plugin lifecycle: database sessions, outbox consumer, graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PluginLifecycle:
    """Manages start / stop for the anime_tracking plugin.

    The instance is stored on the Context for access by commands and the
    outbox dispatcher. In production `Context` is the AstrBot context; in
    tests a fake context with the same interface can be used.
    """

    def __init__(self, context: Any = None) -> None:
        self._context = context
        self._running = False
        self._tasks: list[asyncio.Task[object]] = []

    @classmethod
    def from_context(cls, context: Any) -> PluginLifecycle:
        key = "__anime_tracking_lifecycle__"
        obj = getattr(context, key, None)
        if obj is None:
            obj = cls(context)
            setattr(context, key, obj)
        return obj  # type: ignore[no-any-return]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("anime_tracking plugin started")

    async def shutdown(self) -> None:
        if not self._running:
            return
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        logger.info("anime_tracking plugin shut down")

    @property
    def running(self) -> bool:
        return self._running


__all__ = ["PluginLifecycle"]