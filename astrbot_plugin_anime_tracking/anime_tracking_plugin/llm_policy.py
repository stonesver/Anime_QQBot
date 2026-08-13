"""Per-event policy guard for AstrBot's native LLM conversation path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .readonly_tool import ReadonlyToolStatus

ANIME_ONLY_HELP = (
    "这个群未开启通用聊天，我目前只处理番剧查询。"
    "可以 @我 问“今天播什么”“本周番剧”“搜索 胆大党”或“我的订阅”。"
    "订阅和退订请使用 /番剧 固定命令。"
)

TOOL_FAILURE_HELP = (
    "番剧查询没有成功，我不会根据模型猜测结果。请稍后重试，"
    "或使用 /番剧 今天、/番剧 本周、/番剧 搜索 <关键词>。"
)

ANIME_ONLY_RUNTIME_HINT = """<anime_assistant_policy>
当前群未开启通用聊天。你只能协助番剧相关查询。
番剧事实必须先调用 anime_readonly_query，并且只根据工具 content 组织答案，不得猜测。
支持：今天、本周、季度、搜索、详情、下一集、资源详情、我的订阅。
订阅、退订、修改设置属于写操作，不得调用工具代替执行；提示用户使用 /番剧 固定命令。
非番剧问题只做简短能力提示，不要回答问题本身。
</anime_assistant_policy>"""

GENERAL_CHAT_RUNTIME_HINT = """<anime_assistant_policy>
番剧事实查询优先调用 anime_readonly_query，并且只根据工具 content 组织答案，不得猜测。
订阅、退订、修改设置属于写操作，不得调用工具代替执行；提示用户使用 /番剧 固定命令。
</anime_assistant_policy>"""


@dataclass
class _TurnState:
    general_chat_enabled: bool
    tool_status: ReadonlyToolStatus | None = None


class LLMPolicyGuard:
    """Keep one small state record for each in-flight group mention."""

    def __init__(self) -> None:
        self._turns: dict[tuple[str, str], _TurnState] = {}

    def begin(self, event: Any, *, general_chat_enabled: bool) -> None:
        self._turns[_event_key(event)] = _TurnState(general_chat_enabled)

    def mark_tool_result(self, event: Any, status: ReadonlyToolStatus) -> None:
        state = self._turns.get(_event_key(event))
        if state is not None:
            state.tool_status = status

    def finish(self, event: Any, completion_text: str) -> str:
        state = self._turns.pop(_event_key(event), None)
        if state is None:
            return completion_text
        if state.tool_status in {
            ReadonlyToolStatus.INVALID_REQUEST,
            ReadonlyToolStatus.UNAVAILABLE,
        }:
            return TOOL_FAILURE_HELP
        if state.tool_status in {ReadonlyToolStatus.OK, ReadonlyToolStatus.NOT_FOUND}:
            return completion_text
        if state.general_chat_enabled:
            return completion_text
        return ANIME_ONLY_HELP


def runtime_hint(*, general_chat_enabled: bool) -> str:
    return GENERAL_CHAT_RUNTIME_HINT if general_chat_enabled else ANIME_ONLY_RUNTIME_HINT


def _event_key(event: Any) -> tuple[str, str]:
    message_obj = getattr(event, "message_obj", None)
    group_id = getattr(event, "group_id", None) or getattr(message_obj, "group_id", None)
    message_id = getattr(event, "message_id", None) or getattr(message_obj, "message_id", None)
    fallback = getattr(event, "unified_msg_origin", None) or str(id(event))
    return str(group_id or ""), str(message_id or fallback)


__all__ = [
    "ANIME_ONLY_HELP",
    "ANIME_ONLY_RUNTIME_HINT",
    "GENERAL_CHAT_RUNTIME_HINT",
    "TOOL_FAILURE_HELP",
    "LLMPolicyGuard",
    "runtime_hint",
]
