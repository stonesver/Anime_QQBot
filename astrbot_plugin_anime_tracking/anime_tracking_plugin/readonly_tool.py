"""Strict read-only boundary between AstrBot LLM tools and Anime Core."""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from anime_qqbot.application import ChatContext, Intent, IntentKind

from .adapter import Reply

logger = logging.getLogger(__name__)


class ReadonlyAnimeAction(StrEnum):
    TODAY = "today"
    WEEK = "week"
    SEASON = "season"
    SEARCH = "search"
    DETAIL = "detail"
    RESOURCE_DETAIL = "resource_detail"
    NEXT = "next"
    MY_SUBSCRIPTIONS = "my_subscriptions"


class ReadonlyToolStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    UNAVAILABLE = "unavailable"


_INTENT_KINDS: dict[ReadonlyAnimeAction, IntentKind] = {
    ReadonlyAnimeAction.TODAY: IntentKind.TODAY,
    ReadonlyAnimeAction.WEEK: IntentKind.WEEK,
    ReadonlyAnimeAction.SEASON: IntentKind.SEASON,
    ReadonlyAnimeAction.SEARCH: IntentKind.SEARCH,
    ReadonlyAnimeAction.DETAIL: IntentKind.DETAIL,
    ReadonlyAnimeAction.RESOURCE_DETAIL: IntentKind.RESOURCE_DETAIL,
    ReadonlyAnimeAction.NEXT: IntentKind.NEXT,
    ReadonlyAnimeAction.MY_SUBSCRIPTIONS: IntentKind.MY_SUBSCRIPTIONS,
}


@dataclass(frozen=True)
class ReadonlyAnimeRequest:
    action: ReadonlyAnimeAction
    query: str | None = None
    target_date: str | None = None
    year: int | None = None
    season: str | None = None
    episode: str | None = None
    selection: int | None = None

    @classmethod
    def from_tool_args(
        cls,
        *,
        action: str,
        query: str | None = None,
        date: str | None = None,
        year: int | None = None,
        season: str | None = None,
        episode: str | None = None,
        selection: int | None = None,
    ) -> ReadonlyAnimeRequest:
        try:
            readonly_action = ReadonlyAnimeAction(action)
        except ValueError as exc:
            raise ValueError(f"unsupported readonly action: {action}") from exc

        normalized_query = _optional_text(query)
        normalized_episode = _optional_text(episode)
        normalized_date = _optional_text(date)
        if normalized_date is not None:
            try:
                parsed_date = datetime.date.fromisoformat(normalized_date)
            except ValueError as exc:
                raise ValueError("date must use YYYY-MM-DD") from exc
            normalized_date = parsed_date.isoformat()
        if season is not None and season not in {"冬", "春", "夏", "秋"}:
            raise ValueError("season must be one of 冬, 春, 夏, 秋")
        if year is not None and (isinstance(year, bool) or not 2000 <= year <= 2100):
            raise ValueError("year must be between 2000 and 2100")
        if selection is not None and (isinstance(selection, bool) or not 1 <= selection <= 20):
            raise ValueError("selection must be between 1 and 20")
        if readonly_action == ReadonlyAnimeAction.SEARCH and normalized_query is None:
            raise ValueError("search requires query")
        if (
            readonly_action
            in {
                ReadonlyAnimeAction.DETAIL,
                ReadonlyAnimeAction.RESOURCE_DETAIL,
                ReadonlyAnimeAction.NEXT,
            }
            and normalized_query is None
            and selection is None
        ):
            raise ValueError("this action requires query or selection")
        if selection is not None and readonly_action not in {
            ReadonlyAnimeAction.DETAIL,
            ReadonlyAnimeAction.RESOURCE_DETAIL,
            ReadonlyAnimeAction.NEXT,
        }:
            raise ValueError("selection is not supported for this action")

        return cls(
            action=readonly_action,
            query=normalized_query,
            target_date=normalized_date,
            year=year,
            season=season,
            episode=normalized_episode,
            selection=selection,
        )

    def to_intent(self) -> Intent:
        return Intent(
            kind=_INTENT_KINDS[self.action],
            query=(self.target_date if self.action == ReadonlyAnimeAction.TODAY else self.query),
            season_year=self.year,
            season_name=self.season,
            episode_label=self.episode,
            selection_number=self.selection,
            raw=f"llm_tool:{self.action.value}",
        )


@dataclass(frozen=True)
class ReadonlyToolResult:
    status: ReadonlyToolStatus
    action: ReadonlyAnimeAction
    content: str
    candidate_count: int = 0
    truncated: bool = False

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status.value,
                "action": self.action.value,
                "content": self.content,
                "candidate_count": self.candidate_count,
                "truncated": self.truncated,
                "instruction": "只根据 content 回答，不要补写数据库中没有的信息。",
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class ReadonlyToolOutcome:
    result: ReadonlyToolResult
    reply: Reply | None = None


class ReadonlyIntentAdapter(Protocol):
    async def handle_intent(
        self,
        *,
        ctx: ChatContext,
        intent: Intent,
        now: datetime.datetime | None = None,
    ) -> Reply: ...

    async def persist_candidates(
        self,
        *,
        ctx: ChatContext,
        reply: Reply,
        now: datetime.datetime,
        result_message_id: str | None = None,
    ) -> None: ...


class ReadonlyAnimeExecutor:
    """Execute only the eight approved query intents for the current event identity."""

    def __init__(self, adapter: ReadonlyIntentAdapter, *, max_content_chars: int = 12_000) -> None:
        self._adapter = adapter
        self._max_content_chars = max_content_chars

    async def execute(
        self,
        *,
        ctx: ChatContext,
        request: ReadonlyAnimeRequest,
        now: datetime.datetime,
    ) -> ReadonlyToolOutcome:
        intent = request.to_intent()
        if request.action == ReadonlyAnimeAction.SEASON:
            local_now = now.astimezone(ctx.timezone)
            intent = replace(
                intent,
                season_year=intent.season_year or local_now.year,
                season_name=intent.season_name or _season_for_month(local_now.month),
            )
        try:
            reply = await self._adapter.handle_intent(
                ctx=ctx,
                intent=intent,
                now=now,
            )
            if reply.candidate_items:
                await self._adapter.persist_candidates(ctx=ctx, reply=reply, now=now)
        except Exception:
            logger.exception("readonly anime intent failed", extra={"action": request.action.value})
            return ReadonlyToolOutcome(
                ReadonlyToolResult(
                    status=ReadonlyToolStatus.UNAVAILABLE,
                    action=request.action,
                    content="番剧查询暂时不可用，请稍后重试；固定 /番剧 命令仍可使用。",
                )
            )
        return ReadonlyToolOutcome(self._to_result(request.action, reply), reply)

    def _to_result(self, action: ReadonlyAnimeAction, reply: Reply) -> ReadonlyToolResult:
        if reply.candidate_items:
            content = "\n".join(
                f"{index}. {item.title}"
                for index, item in enumerate(reply.candidate_items, start=1)
            )
            return self._bounded_result(
                status=ReadonlyToolStatus.OK,
                action=action,
                content=content,
                candidate_count=len(reply.candidate_items),
            )
        if reply.kind == "error":
            if reply.error and "被屏蔽" in reply.error:
                return self._bounded_result(
                    status=ReadonlyToolStatus.OK,
                    action=action,
                    content=reply.error,
                )
            return ReadonlyToolResult(
                status=ReadonlyToolStatus.UNAVAILABLE,
                action=action,
                content=f"番剧查询未完成：{reply.error or '未知错误'}",
            )
        content = (
            reply.fallback_text
            or "\n".join(block.text for block in reply.blocks if block.text).strip()
        )
        status = (
            ReadonlyToolStatus.NOT_FOUND
            if any(marker in content for marker in _NOT_FOUND_MARKERS)
            else ReadonlyToolStatus.OK
        )
        return self._bounded_result(status=status, action=action, content=content)

    def _bounded_result(
        self,
        *,
        status: ReadonlyToolStatus,
        action: ReadonlyAnimeAction,
        content: str,
        candidate_count: int = 0,
    ) -> ReadonlyToolResult:
        truncated = len(content) > self._max_content_chars
        if truncated:
            content = content[: self._max_content_chars].rstrip() + "\n…结果已截断"
        return ReadonlyToolResult(
            status=status,
            action=action,
            content=content,
            candidate_count=candidate_count,
            truncated=truncated,
        )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:200] or None


def _season_for_month(month: int) -> str:
    return ("冬", "春", "夏", "秋")[(month - 1) // 3]


_NOT_FOUND_MARKERS = (
    "没有即将放送",
    "没有已收录",
    "未找到匹配",
    "找不到对应番剧",
    "当前没有订阅",
    "暂无",
    "暂无下一集",
    "暂无最近资源",
)


__all__ = [
    "ReadonlyAnimeAction",
    "ReadonlyAnimeExecutor",
    "ReadonlyAnimeRequest",
    "ReadonlyIntentAdapter",
    "ReadonlyToolOutcome",
    "ReadonlyToolResult",
    "ReadonlyToolStatus",
]
