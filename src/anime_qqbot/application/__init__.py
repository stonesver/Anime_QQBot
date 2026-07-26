"""Application layer: platform-neutral chat context and intent types."""

from anime_qqbot.application.context import ChatContext
from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.module import (
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
