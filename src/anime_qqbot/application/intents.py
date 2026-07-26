"""Closed Intent types for fixed commands (Task 6).

Each Intent is a dataclass that captures the user-visible command and
its parsed arguments. The AstrBot adapter parses the raw message into
one of these and dispatches to the matching application use case.

State-changing intents set `requires_confirmation=True` so that natural
language inputs always go through a confirmation state machine. Fixed
commands skip the prompt but still go through the same use case so the
behaviour is identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class IntentKind(StrEnum):
    TODAY = "today"
    WEEK = "week"
    SEASON = "season"
    SEARCH = "search"
    DETAIL = "detail"
    NEXT = "next"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    MY_SUBSCRIPTIONS = "my_subscriptions"
    SUBSCRIPTION_SETTINGS = "subscription_settings"
    STATUS = "status"
    MAPPING_PENDING = "mapping_pending"
    HELP = "help"


_STATE_CHANGING: frozenset[IntentKind] = frozenset(
    {
        IntentKind.SUBSCRIBE,
        IntentKind.UNSUBSCRIBE,
        IntentKind.SUBSCRIPTION_SETTINGS,
    }
)


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    query: str | None = None
    anime_id: str | None = None
    season_year: int | None = None
    season_name: str | None = None
    language: str | None = None
    subtitle_groups: tuple[str, ...] = ()
    resolutions: tuple[str, ...] = ()
    requires_confirmation: bool = False
    raw: str = ""

    def __post_init__(self) -> None:
        if self.kind in _STATE_CHANGING:
            # State-change intents always require confirmation so the
            # application layer can re-display the resulting state.
            if not self.requires_confirmation:
                object.__setattr__(self, "requires_confirmation", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "query": self.query,
            "anime_id": self.anime_id,
            "season_year": self.season_year,
            "season_name": self.season_name,
            "language": self.language,
            "subtitle_groups": list(self.subtitle_groups),
            "resolutions": list(self.resolutions),
            "requires_confirmation": self.requires_confirmation,
            "raw": self.raw,
        }


__all__ = ["Intent", "IntentKind"]
