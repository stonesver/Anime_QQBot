"""Registered AstrBot command handlers (Task 9).

Each handler wraps the EventAdapter, passing the message fields extracted
from the AstrMessageEvent. Command registration via AstrBot's decorator
is guarded so the module compiles without the AstrBot runtime.
"""

from __future__ import annotations

from typing import Any

from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import EventAdapter
from astrbot_plugin_anime_tracking.anime_tracking_plugin.lifecycle import (
    PluginLifecycle,
)


class CommandHandlers:
    """Collection of command handler functions.

    Each method extracts the relevant fields from the AstrBot event and
    delegates to the cross-platform EventAdapter. The lifecycle reference
    provides the database session and context.
    """

    def __init__(self, lifecycle: PluginLifecycle) -> None:
        self._lifecycle = lifecycle
        self._adapter = EventAdapter()

    # In production, AstrBot's decorator maps group-level commands to these
    # methods. Tests call them directly with fake events.

    async def on_fixed_command(self, event: Any) -> Any:
        """Handle a fixed /番剧 subcommand."""
        message = getattr(event, "message_str", "") or ""
        if not message:
            return None

        sender = getattr(event, "sender", None)
        user_id = str(getattr(sender, "user_id", "unknown"))
        nickname = getattr(sender, "nickname", "") or user_id
        group_id = str(getattr(event, "group_id", ""))

        reply = await self._adapter.handle_message(
            platform="qq",
            group_id=group_id,
            user_id=user_id,
            display_name=nickname,
            unified_msg_origin=getattr(event, "unified_msg_origin", None),
            content=message,
        )

        # Rendering to AstrBot chain happens in rendering.py.
        from astrbot_plugin_anime_tracking.anime_tracking_plugin.rendering import (
            render_reply,
        )

        return await render_reply(reply, event)


__all__ = ["CommandHandlers"]
