"""Platform-neutral chat context (Task 6).

The chat context captures the minimum information required by an
application use case to do its work: who is asking, where, with what
display name, which unified_msg_origin the AstrBot plugin can use to
push back, the group timezone and whether the actor has admin rights.

The context deliberately hides the underlying chat framework. The
AstrBot adapter extracts these fields from the AstrMessageEvent; tests
construct the dataclass directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ChatContext:
    platform: str
    group_id: str
    user_id: str
    display_name: str
    unified_msg_origin: str | None
    timezone: ZoneInfo
    is_admin: bool = False

    @classmethod
    def with_timezone(cls, name: str) -> ZoneInfo:
        return ZoneInfo(name)


__all__ = ["ChatContext"]
