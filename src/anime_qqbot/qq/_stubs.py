"""Stub types that replace the deleted qq/ module (Task 10).

These types existed in qq/contracts.py and qq/gateway.py before they
were deleted. Modules that still reference them during the v0.2
transition import from here instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QQEventType(StrEnum):
    GROUP_ADDED = "group_added"
    GROUP_REMOVED = "group_removed"
    ACTIVE_MESSAGES_ENABLED = "active_messages_enabled"
    ACTIVE_MESSAGES_DISABLED = "active_messages_disabled"
    GROUP_MESSAGE = "group_message"


class MemberRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class DeliveryResult(StrEnum):
    SUCCESS = "success"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass
class OutboundMessage:
    text: str
    mentions: list[str] = field(default_factory=list)


from enum import StrEnum as _StrEnum  # noqa: E402


class _FakeDeliveryOutcomeEnum(_StrEnum):
    SUCCESS = "success"
    RETRYABLE = "retryable"
    PERMANENT_FAILURE = "permanent_failure"
    UNKNOWN = "unknown"


@dataclass
class DeliveryOutcome:
    outcome: _FakeDeliveryOutcomeEnum = _FakeDeliveryOutcomeEnum.SUCCESS
    retry_after_seconds: int | None = None
    platform_message_id: str | None = None
    error_code: str | None = None


@dataclass
class QQEvent:
    """Stub for the deleted QQEvent from qq/contracts."""

    event_type: QQEventType = QQEventType.GROUP_MESSAGE
    group_openid: str | None = None
    member_openid: str | None = None
    member_role: MemberRole = MemberRole.MEMBER
    timestamp: str = ""
    content: str = ""
    event_id: str = ""


class QQGateway:
    """Stub for the deleted OfficialQQGateway."""

    async def send_group(self, group_openid: str, message: OutboundMessage) -> DeliveryOutcome:
        return DeliveryOutcome(
            outcome=_FakeDeliveryOutcomeEnum.PERMANENT_FAILURE, error_code="qq-gateway-removed"
        )

    async def send_private(self, _member_openid: str, _message: OutboundMessage) -> Any:
        return None


class AgentRuntime:
    """Stub for the deleted agent runtime."""

    pass


__all__ = [
    "AgentRuntime",
    "DeliveryOutcome",
    "DeliveryResult",
    "MemberRole",
    "OutboundMessage",
    "QQEvent",
    "QQEventType",
    "QQGateway",
]
