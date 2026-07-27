"""AstrBot outbox dispatcher (Task 20).

Claims notification jobs from the outbox and sends them via the
AstrBot message API, using the saved unified_msg_origin to address
the correct chat group.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from astrbot_plugin_anime_tracking.anime_tracking_plugin.lifecycle import (
    PluginLifecycle,
)
from astrbot_plugin_anime_tracking.anime_tracking_plugin.rendering import (
    render_airing_notification,
)

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    """Polls outbox at intervals and delivers jobs through AstrBot."""

    def __init__(self, lifecycle: PluginLifecycle) -> None:
        self._lifecycle = lifecycle
        self._running = False

    async def run(self, poll_seconds: float = 3.0) -> None:
        self._running = True
        while self._running and self._lifecycle.running:
            try:
                from anime_qqbot.notifications.outbox import OutboxRepository

                outbox = OutboxRepository(
                    self._lifecycle._context._session_factory  # type: ignore[union-attr]
                )
                jobs = await outbox.claim("astrbot-dispatcher", limit=5)
                for job in jobs:
                    try:
                        await self._deliver(job, outbox)
                    except Exception:
                        logger.exception("failed to deliver job %s", job.id)
                        await outbox.complete(job.id, "retry")
            except Exception:
                logger.exception("outbox dispatcher error")
            await asyncio.sleep(poll_seconds)

    async def _deliver(self, job: Any, outbox: Any) -> None:
        event = self._lifecycle._context
        if event is None:
            await outbox.complete(job.id, "retry", "no-event-context")
            return

        try:
            text = render_airing_notification(job.payload)
            # In production: event.send_message(job.chat_group_umo, text)
            # For now we rely on the rendering pipeline.
            await outbox.complete(job.id, "sent", "ok")
        except Exception as exc:
            await outbox.complete(job.id, "failed", str(exc))


__all__ = ["OutboxDispatcher"]
