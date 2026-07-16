from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class QQEventType(StrEnum):
    GROUP_AT_MESSAGE = "group_at_message"
    C2C_MESSAGE = "c2c_message"
    BUTTON_INTERACTION = "button_interaction"
    GROUP_ADDED = "group_added"
    GROUP_REMOVED = "group_removed"
    ACTIVE_MESSAGES_ENABLED = "active_messages_enabled"
    ACTIVE_MESSAGES_DISABLED = "active_messages_disabled"


class MemberRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@dataclass(frozen=True)
class QQEvent:
    event_id: str
    event_type: QQEventType
    occurred_at: datetime
    content: str = ""
    message_id: str | None = None
    group_openid: str | None = None
    member_openid: str | None = None
    user_openid: str | None = None
    member_role: MemberRole = MemberRole.MEMBER
    reply_deadline: datetime | None = None
    button_data: str | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.event_type is QQEventType.BUTTON_INTERACTION:
            if self.group_openid and not self.member_openid:
                raise ValueError("group interactions require member_openid")
            if not self.group_openid and not self.user_openid:
                raise ValueError("single-chat interactions require user_openid")
            return
        if self.is_group and (not self.group_openid or not self.member_openid):
            raise ValueError("group events require group_openid and member_openid")
        if self.event_type is QQEventType.C2C_MESSAGE and not self.user_openid:
            raise ValueError("C2C events require user_openid")

    @property
    def is_group(self) -> bool:
        if self.event_type is QQEventType.BUTTON_INTERACTION:
            return self.group_openid is not None
        return self.event_type in {
            QQEventType.GROUP_AT_MESSAGE,
            QQEventType.GROUP_ADDED,
            QQEventType.GROUP_REMOVED,
            QQEventType.ACTIVE_MESSAGES_ENABLED,
            QQEventType.ACTIVE_MESSAGES_DISABLED,
        }


@dataclass(frozen=True)
class MessageButton:
    label: str
    data: str


@dataclass(frozen=True)
class OutboundMessage:
    text: str
    markdown: str | None = None
    fallback_markdown: str | None = None
    buttons: tuple[MessageButton, ...] = field(default_factory=tuple)
    mentions: tuple[str, ...] = field(default_factory=tuple)


class DeliveryOutcome(StrEnum):
    SENT = "sent"
    RATE_LIMITED = "rate_limited"
    PERMANENT_FAILURE = "permanent_failure"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeliveryResult:
    outcome: DeliveryOutcome
    platform_message_id: str | None = None
    retry_after_seconds: int | None = None
    error_code: str | None = None
