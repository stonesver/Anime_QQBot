"""Application module exports (Task 6).

This file is the package surface so other modules can do
`from anime_qqbot.application import Intent, IntentKind, ChatContext`.
"""

from __future__ import annotations

from anime_qqbot.application.context import ChatContext
from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.parser import (
    ParseFailure,
    is_internal_id,
    parse_fixed_command,
)

__all__ = [
    "ChatContext",
    "Intent",
    "IntentKind",
    "ParseFailure",
    "is_internal_id",
    "parse_fixed_command",
]
