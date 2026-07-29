"""Normalize AstrBot group events without leaking OneBot-specific details."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventEnvelope:
    platform: str
    group_id: str
    user_id: str
    display_name: str
    role: str
    self_id: str
    message_id: str
    unified_msg_origin: str | None
    text: str
    mentions_bot: bool
    reply_to_message_id: str | None

    @property
    def is_owner(self) -> bool:
        return self.role == "admin"


def from_astrbot_event(event: Any) -> EventEnvelope:
    message_obj = getattr(event, "message_obj", None)
    sender = getattr(message_obj, "sender", None) or getattr(event, "sender", None)
    chain = (
        getattr(message_obj, "message", None)
        or getattr(message_obj, "message_chain", None)
        or getattr(event, "message_chain", None)
        or []
    )
    self_id = _string(getattr(message_obj, "self_id", None) or getattr(event, "self_id", None))
    role = "admin" if getattr(event, "role", "member") == "admin" else "member"
    return EventEnvelope(
        platform="qq",
        group_id=group_id_from_astrbot_event(event),
        user_id=_sender_value(event, sender, "user_id", "get_sender_id"),
        display_name=_sender_value(event, sender, "nickname", "get_sender_name"),
        role=role,
        self_id=self_id,
        message_id=_string(
            getattr(message_obj, "message_id", None) or getattr(event, "message_id", None)
        ),
        unified_msg_origin=getattr(event, "unified_msg_origin", None),
        text=_string(getattr(event, "message_str", "")).strip(),
        mentions_bot=_starts_with_self_at(chain, self_id),
        reply_to_message_id=_reply_id(chain),
    )


def group_id_from_astrbot_event(event: Any) -> str:
    message_obj = getattr(event, "message_obj", None)
    return _string(getattr(event, "group_id", None) or getattr(message_obj, "group_id", None))


def _starts_with_self_at(chain: list[Any], self_id: str) -> bool:
    for component in chain:
        kind = _component_kind(component)
        if kind in {"plain", "text"} and not _component_text(component).strip():
            continue
        if kind not in {"at", "mention"}:
            return False
        target = _component_value(component, "qq", "user_id", "target", "id")
        return bool(self_id and _string(target) == self_id)
    return False


def _reply_id(chain: list[Any]) -> str | None:
    for component in chain:
        if _component_kind(component) in {"reply", "quote"}:
            value = _component_value(component, "id", "message_id", "messageId", "reply_id")
            return _string(value) or None
    return None


def _component_kind(component: Any) -> str:
    if isinstance(component, dict):
        return _string(component.get("type") or component.get("kind")).casefold()
    return str(component.__class__.__name__).casefold()


def _component_text(component: Any) -> str:
    return _string(_component_value(component, "text", "content"))


def _component_value(component: Any, *names: str) -> object:
    if isinstance(component, dict):
        data = component.get("data")
        for name in names:
            if name in component:
                return component[name]
            if isinstance(data, dict) and name in data:
                return data[name]
        return ""
    for name in names:
        value = getattr(component, name, None)
        if value is not None:
            return value
    return ""


def _sender_value(event: Any, sender: Any, attribute: str, method: str) -> str:
    getter = getattr(event, method, None)
    if callable(getter):
        return _string(getter())
    if isinstance(sender, dict):
        return _string(sender.get(attribute, ""))
    return _string(getattr(sender, attribute, ""))


def _string(value: object) -> str:
    return "" if value is None else str(value)


__all__ = ["EventEnvelope", "from_astrbot_event", "group_id_from_astrbot_event"]
