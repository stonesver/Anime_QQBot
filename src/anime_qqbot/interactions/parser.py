"""Anchored parsers for safe direct and mention-based group interactions."""

from __future__ import annotations

import re

from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.parser import ParseFailure, parse_fixed_command
from anime_qqbot.interactions.mention_policy import (
    DEFAULT_MENTION_COMMAND_POLICY,
    MentionCommandPolicy,
)

_DIRECT_EXACT: dict[str, IntentKind] = {
    "今日番剧": IntentKind.TODAY,
    "本周番剧": IntentKind.WEEK,
    "我的追番": IntentKind.MY_SUBSCRIPTIONS,
}
_DIRECT_WITH_QUERY: tuple[tuple[re.Pattern[str], IntentKind], ...] = (
    (re.compile(r"^搜番\s+(.+)$"), IntentKind.SEARCH),
    (re.compile(r"^追番\s+(.+)$"), IntentKind.SUBSCRIBE),
    (re.compile(r"^退订\s+(.+)$"), IntentKind.UNSUBSCRIBE),
)
_NUMBER_RE = re.compile(r"^([1-9]\d?)$")

_EXACT_ACTIONS = {
    "today": IntentKind.TODAY,
    "week": IntentKind.WEEK,
    "my_subscriptions": IntentKind.MY_SUBSCRIPTIONS,
    "help": IntentKind.HELP,
}
_PREFIX_ACTIONS = {
    "search": IntentKind.SEARCH,
    "detail": IntentKind.DETAIL,
    "next": IntentKind.NEXT,
    "resource_detail": IntentKind.RESOURCE_DETAIL,
    "subscribe": IntentKind.SUBSCRIBE,
    "unsubscribe": IntentKind.UNSUBSCRIBE,
}


def parse_direct_shortcut(content: str) -> Intent | ParseFailure:
    raw = _normalize(content)
    if raw.startswith("资源详情"):
        return parse_fixed_command(raw)
    kind = _DIRECT_EXACT.get(raw)
    if kind is not None:
        return Intent(kind=kind, raw=content)
    for pattern, kind in _DIRECT_WITH_QUERY:
        match = pattern.fullmatch(raw)
        if match:
            return _target_intent(kind, match.group(1), raw=content)
    return ParseFailure("not a direct shortcut")


def parse_mention_command(
    content: str,
    *,
    policy: MentionCommandPolicy = DEFAULT_MENTION_COMMAND_POLICY,
) -> Intent | ParseFailure:
    raw = _normalize(content)
    if not raw:
        return Intent(kind=IntentKind.HELP, raw=content)
    for action, kind in _EXACT_ACTIONS.items():
        if raw in policy.aliases[action]:
            return Intent(kind=kind, raw=content)
    for action, kind in _PREFIX_ACTIONS.items():
        for prefix in sorted(policy.aliases[action], key=len, reverse=True):
            marker = f"{prefix} "
            if not raw.startswith(marker):
                continue
            target = raw[len(marker) :].strip()
            if action == "resource_detail":
                return parse_fixed_command(f"资源详情 {target}")
            return _target_intent(kind, target, raw=content)
    number = _selection_number(raw)
    if number is not None:
        return Intent(
            kind=IntentKind.DETAIL,
            selection_number=number,
            raw=content,
        )
    return ParseFailure("not a supported mention command")


def parse_reply_number(content: str) -> Intent | ParseFailure:
    raw = _normalize(content)
    number = _selection_number(raw)
    if number is None:
        return ParseFailure("not a candidate number")
    return Intent(
        kind=IntentKind.DETAIL,
        selection_number=number,
        raw=content,
    )


def _target_intent(kind: IntentKind, target: str, *, raw: str) -> Intent:
    normalized = target.strip()
    number = _selection_number(normalized)
    if number is not None:
        return Intent(kind=kind, selection_number=number, raw=raw)
    return Intent(kind=kind, query=normalized, raw=raw)


def _selection_number(value: str) -> int | None:
    match = _NUMBER_RE.fullmatch(value)
    if match is None:
        return None
    number = int(match.group(1))
    return number if number <= 20 else None


def _normalize(content: str) -> str:
    return re.sub(r"\s+", " ", content.strip())


__all__ = [
    "parse_direct_shortcut",
    "parse_mention_command",
    "parse_reply_number",
]
