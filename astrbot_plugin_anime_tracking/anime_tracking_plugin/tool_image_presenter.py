"""Send one trusted Tool image and stop the current AstrBot Agent."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapter import Reply
from .rendering import reply_to_message_chain

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolImagePresenter:
    asset_root: Path
    stop_settle_seconds: float = 0.55

    async def send(self, event: Any, reply: Reply) -> bool:
        if reply.kind != "image":
            return False
        sender = getattr(event, "send", None)
        if not callable(sender):
            return False
        try:
            chain = reply_to_message_chain(reply, asset_root=self.asset_root)
            await sender(chain)
        except Exception as exc:
            logger.warning(
                "llm_tool_image_send_failed",
                extra={"error_type": type(exc).__name__},
            )
            return False
        set_extra = getattr(event, "set_extra", None)
        if callable(set_extra):
            set_extra("agent_stop_requested", True)
        stopper = getattr(event, "stop_event", None)
        if callable(stopper):
            stopper()
        if self.stop_settle_seconds > 0:
            await asyncio.sleep(self.stop_settle_seconds)
        return True


__all__ = ["ToolImagePresenter"]
