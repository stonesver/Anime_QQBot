"""AstrBot-native FunctionTool for the read-only anime query boundary."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic.dataclasses import dataclass

try:
    from astrbot.core.agent.run_context import ContextWrapper  # type: ignore[import-not-found]
    from astrbot.core.agent.tool import (  # type: ignore[import-not-found]
        FunctionTool,
        ToolExecResult,
    )
    from astrbot.core.astr_agent_context import AstrAgentContext  # type: ignore[import-not-found]
except ModuleNotFoundError:
    ContextWrapper = Any
    AstrAgentContext = Any
    ToolExecResult = str

    class FunctionTool:  # type: ignore[no-redef]
        pass


from anime_qqbot.application import ChatContext
from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent
from anime_qqbot.groups.settings import GroupRuntimeSettingsRepository

from .adapter import EventAdapter
from .event_envelope import from_astrbot_event
from .lifecycle import PluginLifecycle
from .llm_policy import LLMPolicyGuard
from .readonly_tool import (
    ReadonlyAnimeAction,
    ReadonlyAnimeExecutor,
    ReadonlyAnimeRequest,
    ReadonlyToolResult,
    ReadonlyToolStatus,
)

logger = logging.getLogger(__name__)

ANIME_READONLY_TOOL_NAME = "anime_readonly_query"


def _tool_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [action.value for action in ReadonlyAnimeAction],
                "description": "只读动作：今天、本周、季度、搜索、详情、资源、下一集或我的订阅。",
            },
            "query": {
                "type": "string",
                "maxLength": 200,
                "description": "番剧标题或搜索关键词。",
            },
            "date": {
                "type": "string",
                "format": "date",
                "description": "today 动作的可选日期，YYYY-MM-DD。",
            },
            "year": {
                "type": "integer",
                "minimum": 2000,
                "maximum": 2100,
                "description": "season 动作的年份。",
            },
            "season": {
                "type": "string",
                "enum": ["冬", "春", "夏", "秋"],
                "description": "season 动作的季度。",
            },
            "episode": {
                "type": "string",
                "maxLength": 32,
                "description": "resource_detail 动作的可选集数。",
            },
            "selection": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "用户选择上一轮候选结果的编号。",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }


@dataclass(config={"arbitrary_types_allowed": True})
class AnimeReadonlyTool(FunctionTool):  # type: ignore[misc]
    name: str = ANIME_READONLY_TOOL_NAME
    description: str = (
        "查询本机器人数据库中的番剧排期、目录、详情、下一集、资源和当前用户订阅。"
        "严格只读，不支持订阅、退订或修改设置。"
    )
    parameters: dict[str, Any] = Field(default_factory=_tool_parameters)
    lifecycle_provider: Callable[[], Awaitable[PluginLifecycle]] | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )
    policy_guard: LLMPolicyGuard | None = Field(default=None, exclude=True, repr=False)

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        event = context.context.event
        envelope = from_astrbot_event(event)
        if not envelope.group_id or not envelope.user_id or not envelope.mentions_bot:
            return self._finish(
                event,
                ReadonlyToolResult(
                    status=ReadonlyToolStatus.INVALID_REQUEST,
                    action=_safe_action(kwargs.get("action")),
                    content="只允许在 QQ 群中明确 @机器人 后进行只读番剧查询。",
                ),
            )
        try:
            request = ReadonlyAnimeRequest.from_tool_args(
                action=str(kwargs.get("action", "")),
                query=_as_optional_str(kwargs.get("query")),
                date=_as_optional_str(kwargs.get("date")),
                year=_as_optional_int(kwargs.get("year")),
                season=_as_optional_str(kwargs.get("season")),
                episode=_as_optional_str(kwargs.get("episode")),
                selection=_as_optional_int(kwargs.get("selection")),
            )
        except ValueError as exc:
            return self._finish(
                event,
                ReadonlyToolResult(
                    status=ReadonlyToolStatus.INVALID_REQUEST,
                    action=_safe_action(kwargs.get("action")),
                    content=f"查询参数无效：{exc}",
                ),
            )
        if self.lifecycle_provider is None:
            return self._finish(event, _unavailable(request.action))
        try:
            lifecycle = await self.lifecycle_provider()
            if lifecycle.sessions is None:
                return self._finish(event, _unavailable(request.action))
            now = datetime.datetime.now(datetime.UTC)
            group = await ChatGroupRepository(lifecycle.sessions).upsert_group_event(
                GroupEvent(
                    platform=envelope.platform,
                    external_group_id=envelope.group_id,
                    external_user_id=envelope.user_id,
                    display_name=envelope.display_name,
                    unified_msg_origin=envelope.unified_msg_origin,
                    timestamp=now,
                )
            )
            policy = await GroupRuntimeSettingsRepository(lifecycle.sessions).get_policy(group.id)
            chat_context = ChatContext(
                platform=envelope.platform,
                group_id=envelope.group_id,
                user_id=envelope.user_id,
                display_name=envelope.display_name,
                unified_msg_origin=envelope.unified_msg_origin,
                timezone=ZoneInfo(policy.timezone),
                is_admin=envelope.is_owner,
            )
            result = await ReadonlyAnimeExecutor(
                EventAdapter(sessions=lifecycle.sessions)
            ).execute(ctx=chat_context, request=request, now=now)
        except Exception:
            logger.exception("anime_readonly_query failed")
            result = _unavailable(request.action)
        return self._finish(event, result)

    def _finish(self, event: Any, result: ReadonlyToolResult) -> str:
        if self.policy_guard is not None:
            self.policy_guard.mark_tool_result(event, result.status)
        return result.to_json()


def _safe_action(value: object) -> ReadonlyAnimeAction:
    try:
        return ReadonlyAnimeAction(str(value))
    except ValueError:
        return ReadonlyAnimeAction.SEARCH


def _as_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _unavailable(action: ReadonlyAnimeAction) -> ReadonlyToolResult:
    return ReadonlyToolResult(
        status=ReadonlyToolStatus.UNAVAILABLE,
        action=action,
        content="番剧查询暂时不可用，请稍后重试；固定 /番剧 命令仍可使用。",
    )


__all__ = ["ANIME_READONLY_TOOL_NAME", "AnimeReadonlyTool"]
