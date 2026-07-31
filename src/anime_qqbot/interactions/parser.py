"""Anchored parsers for safe direct and mention-based group interactions."""

from __future__ import annotations

import re

from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.parser import ParseFailure, parse_fixed_command

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
_MENTION_EXACT: dict[str, IntentKind] = {
    "今天有什么": IntentKind.TODAY,
    "今天有什么番": IntentKind.TODAY,
    "今日番剧": IntentKind.TODAY,
    "本周有什么": IntentKind.WEEK,
    "本周番剧": IntentKind.WEEK,
    "我的追番": IntentKind.MY_SUBSCRIPTIONS,
    "我的订阅": IntentKind.MY_SUBSCRIPTIONS,
    "帮助": IntentKind.HELP,
}
_MENTION_PATTERNS: tuple[tuple[re.Pattern[str], IntentKind], ...] = (
    (re.compile(r"^(?:搜番|搜索|找番)\s+(.+)$"), IntentKind.SEARCH),
    (re.compile(r"^(?:看|详情)\s+(.+)$"), IntentKind.DETAIL),
    (re.compile(r"^(?:追番|订阅)\s+(.+)$"), IntentKind.SUBSCRIBE),
    (re.compile(r"^(?:退订|取消订阅)\s+(.+)$"), IntentKind.UNSUBSCRIBE),
)
_NUMBER_RE = re.compile(r"^([1-9]\d?)$")


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


def parse_mention_command(content: str) -> Intent | ParseFailure:
    raw = _normalize(content)
    if not raw:
        return Intent(kind=IntentKind.HELP, raw=content)
    kind = _MENTION_EXACT.get(raw)
    if kind is not None:
        return Intent(kind=kind, raw=content)
    for pattern, kind in _MENTION_PATTERNS:
        match = pattern.fullmatch(raw)
        if match:
            return _target_intent(kind, match.group(1), raw=content)
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
