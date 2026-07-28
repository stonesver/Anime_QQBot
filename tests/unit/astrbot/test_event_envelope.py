from __future__ import annotations

from dataclasses import dataclass, field

from anime_tracking_plugin.event_envelope import from_astrbot_event


@dataclass
class Sender:
    user_id: str = "u1"
    nickname: str = "alice"


@dataclass
class Message:
    self_id: str = "bot1"
    message_id: str = "msg1"
    group_id: str = "g1"
    sender: Sender = field(default_factory=Sender)
    message: list[dict[str, object]] = field(default_factory=list)


@dataclass
class Event:
    message_obj: Message
    message_str: str = "搜番 芙莉莲"
    group_id: str = "g1"
    role: str = "member"
    unified_msg_origin: str = "umo:g1"
    raw_message: str = "must-not-be-retained"


def test_self_mention_and_reply_are_normalized() -> None:
    event = Event(
        Message(
            message=[
                {"type": "At", "data": {"qq": "bot1"}},
                {"type": "Plain", "text": " 搜番 芙莉莲"},
                {"type": "Reply", "data": {"id": "result1"}},
            ]
        ),
        role="admin",
    )

    envelope = from_astrbot_event(event)

    assert envelope.mentions_bot is True
    assert envelope.reply_to_message_id == "result1"
    assert envelope.is_owner is True
    assert not hasattr(envelope, "raw_message")


def test_other_user_mention_does_not_wake_bot() -> None:
    event = Event(Message(message=[{"type": "At", "data": {"qq": "someone-else"}}]))

    assert from_astrbot_event(event).mentions_bot is False


def test_qq_group_sender_role_is_ignored() -> None:
    message = Message(sender=Sender())
    message.sender.role = "owner"  # type: ignore[attr-defined]
    event = Event(message, role="member")

    assert from_astrbot_event(event).is_owner is False
