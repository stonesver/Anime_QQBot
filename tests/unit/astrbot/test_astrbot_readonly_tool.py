from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anime_tracking_plugin.astrbot_tool import AnimeReadonlyTool

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from astrbot_plugin_anime_tracking.main import AnimeTrackingPlugin


class PluginContext:
    def __init__(self) -> None:
        self.tools = []
        self.routes = []

    def add_llm_tools(self, *tools) -> None:
        self.tools.extend(tools)

    def register_web_api(self, route, handler, methods, description) -> None:
        self.routes.append((route, handler, methods, description))


def test_tool_schema_exposes_actions_but_never_identity_fields() -> None:
    tool = AnimeReadonlyTool()

    properties = tool.parameters["properties"]
    assert properties["action"]["enum"] == [
        "today",
        "week",
        "season",
        "search",
        "detail",
        "resource_detail",
        "next",
        "my_subscriptions",
    ]
    assert set(properties).isdisjoint(
        {"group_id", "user_id", "qq", "platform", "unified_msg_origin"}
    )


def test_plugin_registers_native_readonly_tool() -> None:
    context = PluginContext()

    AnimeTrackingPlugin(context)

    assert [tool.name for tool in context.tools] == ["anime_readonly_query"]


@pytest.mark.asyncio
async def test_llm_hooks_inject_policy_and_fail_closed_without_tool() -> None:
    context = PluginContext()
    plugin = AnimeTrackingPlugin(context)
    plugin._general_chat_enabled = AsyncMock(return_value=False)
    event = SimpleNamespace(
        group_id="g1",
        message_id="m1",
        message_str="今天播什么",
        unified_msg_origin="umo:g1",
        role="member",
        message_obj=SimpleNamespace(
            self_id="bot1",
            group_id="g1",
            message_id="m1",
            sender={"user_id": "u1", "nickname": "alice"},
            message=[
                {"type": "At", "data": {"qq": "bot1"}},
                {"type": "Plain", "text": "今天播什么"},
            ],
        ),
    )
    request = SimpleNamespace(extra_user_content_parts=[])

    await plugin._on_llm_request(event, request)

    assert len(request.extra_user_content_parts) == 1
    assert "未开启通用聊天" in request.extra_user_content_parts[0].text

    response = SimpleNamespace(completion_text="模型自行回答的天气内容")
    await plugin._on_agent_done(event, SimpleNamespace(), response)
    assert "只处理番剧查询" in response.completion_text
