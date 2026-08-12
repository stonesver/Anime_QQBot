from __future__ import annotations

from types import SimpleNamespace

from anime_tracking_plugin.llm_policy import (
    ANIME_ONLY_HELP,
    TOOL_FAILURE_HELP,
    LLMPolicyGuard,
)
from anime_tracking_plugin.readonly_tool import ReadonlyToolStatus


def _event(message_id: str = "m1") -> SimpleNamespace:
    return SimpleNamespace(
        message_id=message_id,
        group_id="g1",
        unified_msg_origin="umo:g1",
    )


def test_chat_disabled_replaces_response_without_successful_anime_tool() -> None:
    guard = LLMPolicyGuard()
    event = _event()
    guard.begin(event, general_chat_enabled=False)

    assert guard.finish(event, "巴黎是法国首都") == ANIME_ONLY_HELP


def test_chat_disabled_keeps_grounded_response_after_readonly_tool() -> None:
    guard = LLMPolicyGuard()
    event = _event()
    guard.begin(event, general_chat_enabled=False)
    guard.mark_tool_result(event, ReadonlyToolStatus.OK)

    assert guard.finish(event, "今天有两部番剧") == "今天有两部番剧"


def test_tool_failure_never_falls_back_to_model_guess() -> None:
    guard = LLMPolicyGuard()
    event = _event()
    guard.begin(event, general_chat_enabled=True)
    guard.mark_tool_result(event, ReadonlyToolStatus.UNAVAILABLE)

    assert guard.finish(event, "我猜今天播出……") == TOOL_FAILURE_HELP


def test_chat_enabled_keeps_general_response_when_no_tool_was_used() -> None:
    guard = LLMPolicyGuard()
    event = _event()
    guard.begin(event, general_chat_enabled=True)

    assert guard.finish(event, "普通聊天回答") == "普通聊天回答"


def test_guard_correlates_framework_event_wrappers_by_message_id() -> None:
    guard = LLMPolicyGuard()
    request_event = _event()
    tool_event = _event()
    guard.begin(request_event, general_chat_enabled=False)
    guard.mark_tool_result(tool_event, ReadonlyToolStatus.UNAVAILABLE)

    assert guard.finish(tool_event, "模型猜测结果") == TOOL_FAILURE_HELP
