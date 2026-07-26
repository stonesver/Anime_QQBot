"""AstrBot event adapter (Task 9).

Converts AstrMessageEvent -> ChatContext, dispatches fixed commands to
the intent parser and forwards the resulting Intent (together with the
context) to the Anime Core use cases. Returns a platform-neutral Reply
that rendering.py maps to AstrBot message components.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from anime_qqbot.application import (
    ChatContext,
    Intent,
    IntentKind,
    ParseFailure,
    parse_fixed_command,
)

# ---------------------------------------------------------------------------
# Platform-neutral reply types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplyBlock:
    """One text or image segment of a reply."""

    text: str = ""

    # image data will be added when cover proxy is reconnected
    # image_url: str | None = None


@dataclass
class Reply:
    kind: str = "text"
    blocks: list[ReplyBlock] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    at_user_ids: list[str] = field(default_factory=list)
    error: str | None = None


def help_reply() -> Reply:
    return Reply(
        kind="help",
        blocks=[
            ReplyBlock(
                text=(
                    "/番剧 今天 [YYYY-MM-DD]\n"
                    "/番剧 本周\n"
                    "/番剧 季度 [年份] [冬|春|夏|秋]\n"
                    "/番剧 搜索 <关键词>\n"
                    "/番剧 详情 <内部ID|关键词>\n"
                    "/番剧 下次 <内部ID|关键词>\n"
                    "/番剧 订阅 <内部ID|关键词>\n"
                    "/番剧 取消订阅 <内部ID|关键词>\n"
                    "/番剧 我的订阅\n"
                    "/番剧 订阅设置 <内部ID>\n"
                    "/番剧 状态\n"
                    "/番剧 映射待处理"
                )
            )
        ],
    )


# ---------------------------------------------------------------------------
# Use case handler type
# ---------------------------------------------------------------------------

UseCaseHandler = Callable[[ChatContext, Intent], Coroutine[Any, Any, Reply]]


# ---------------------------------------------------------------------------
# Default handlers (stubs — implemented in later tasks)
# ---------------------------------------------------------------------------


async def _handle_search(ctx: ChatContext, intent: Intent) -> Reply:
    return Reply(kind="text", blocks=[ReplyBlock(text=f"搜索: {intent.query} — 暂无结果")])


async def _handle_detail(ctx: ChatContext, intent: Intent) -> Reply:
    return Reply(kind="text", blocks=[ReplyBlock(text=f"详情: {intent.anime_id or intent.query}")])


async def _handle_subscribe(ctx: ChatContext, intent: Intent) -> Reply:
    return Reply(
        kind="text",
        blocks=[ReplyBlock(text=f"订阅: {intent.anime_id or intent.query} — 功能开发中")],
    )


_DEFAULT_HANDLERS: dict[IntentKind, UseCaseHandler] = {
    IntentKind.TODAY: _handle_search,
    IntentKind.WEEK: _handle_search,
    IntentKind.SEASON: _handle_search,
    IntentKind.SEARCH: _handle_search,
    IntentKind.DETAIL: _handle_detail,
    IntentKind.NEXT: _handle_detail,
    IntentKind.SUBSCRIBE: _handle_subscribe,
    IntentKind.UNSUBSCRIBE: _handle_subscribe,
    IntentKind.MY_SUBSCRIPTIONS: _handle_subscribe,
    IntentKind.SUBSCRIPTION_SETTINGS: _handle_subscribe,
    IntentKind.STATUS: _handle_subscribe,
    IntentKind.MAPPING_PENDING: _handle_subscribe,
}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class EventAdapter:
    """Glue between AstrBot event and Anime Core use cases."""

    def __init__(self, *, handlers: dict[IntentKind, UseCaseHandler] | None = None) -> None:
        self._handlers = handlers or _DEFAULT_HANDLERS

    async def handle_message(
        self,
        *,
        platform: str,
        group_id: str,
        user_id: str,
        display_name: str,
        unified_msg_origin: str | None,
        content: str,
        is_admin: bool = False,
        timezone_name: str = "Asia/Shanghai",
    ) -> Reply:
        ctx = ChatContext(
            platform=platform,
            group_id=group_id,
            user_id=user_id,
            display_name=display_name,
            unified_msg_origin=unified_msg_origin,
            timezone=ZoneInfo(timezone_name),
            is_admin=is_admin,
        )

        result = parse_fixed_command(content)
        if isinstance(result, ParseFailure):
            return Reply(kind="error", error=result.reason)

        intent = result
        if intent.kind == IntentKind.HELP:
            return help_reply()

        handler = self._handlers.get(intent.kind)
        if handler is None:
            return Reply(kind="error", error=f"unknown intent: {intent.kind.value}")

        return await handler(ctx, intent)


__all__ = [
    "EventAdapter",
    "Reply",
    "ReplyBlock",
    "UseCaseHandler",
    "help_reply",
]
