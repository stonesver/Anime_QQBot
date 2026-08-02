"""Unit tests for the EventAdapter (Task 9)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anime_qqbot.application.context import ChatContext
from anime_qqbot.application.intents import IntentKind
from anime_qqbot.application.use_cases import QueryResult
from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import (
    EventAdapter,
    Reply,
    help_reply,  # noqa: F401
)


class ScheduleBuilder:
    def __init__(self) -> None:
        self.called = False

    async def build_weekly(self, *, rows, ctx, fallback, now):
        self.called = True
        return Reply.from_image(Path("weekly.png"))


async def _noop(ctx, intent):
    """Stub handler returns a simple text reply."""
    return Reply(kind="text", blocks=[])


async def test_help_command_returns_full_help() -> None:
    adapter = EventAdapter(sessions=None)

    reply = await adapter.handle_message(
        platform="qq",
        group_id="123",
        user_id="456",
        display_name="test",
        unified_msg_origin=None,
        content="/番剧 帮助",
    )

    assert reply.kind == "help"
    assert any("本周" in b.text for b in reply.blocks)


async def test_empty_group_identity_is_rejected_before_dispatch() -> None:
    adapter = EventAdapter(sessions=None)

    reply = await adapter.handle_message(
        platform="qq",
        group_id="",
        user_id="456",
        display_name="test",
        unified_msg_origin="napcat:GroupMessage:1091724800",
        content="/番剧 订阅 测试番剧",
    )

    assert reply.error == "无法识别当前群或用户，未执行操作"


@pytest.mark.parametrize(
    "content",
    [
        "/番剧 今天",
        "/番剧 本周",
        "/番剧 季度 夏",
        "/番剧 搜索 test",
        "/番剧 详情 test",
        "/番剧 下次 abc",
        "/番剧 我的订阅",
        "/番剧 状态",
        "/番剧 映射待处理",
    ],
)
async def test_all_fixed_commands_parse_and_dispatch(content: str) -> None:
    adapter = EventAdapter(sessions=None)

    reply = await adapter.handle_message(
        platform="qq",
        group_id="123",
        user_id="456",
        display_name="test",
        unified_msg_origin=None,
        content=content,
    )

    assert reply.kind in ("text", "error")
    # Unknown commands return a specific error, not a crash.
    assert not isinstance(reply, type(None))


async def test_unknown_subcommand_returns_error() -> None:
    adapter = EventAdapter(sessions=None)

    reply = await adapter.handle_message(
        platform="qq",
        group_id="123",
        user_id="456",
        display_name="test",
        unified_msg_origin=None,
        content="/番剧 未知",
    )

    assert reply.error is not None


async def test_non_fixed_command_returns_error() -> None:
    adapter = EventAdapter(sessions=None)

    reply = await adapter.handle_message(
        platform="qq",
        group_id="123",
        user_id="456",
        display_name="test",
        unified_msg_origin=None,
        content="今天",
    )

    assert reply.error is not None


async def test_context_is_built_with_timezone() -> None:
    captured: dict = {}

    async def _capture(ctx, intent):
        captured["timezone"] = str(ctx.timezone)
        captured["group_id"] = ctx.group_id
        return Reply(kind="text", blocks=[])

    adapter = EventAdapter(sessions=None, handlers={"today": _capture})

    await adapter.handle_message(
        platform="qq",
        group_id="987",
        user_id="u1",
        display_name="dname",
        unified_msg_origin="umo",
        content="/番剧 今天",
        timezone_name="Asia/Tokyo",
    )

    assert captured["timezone"] == "Asia/Tokyo"
    assert captured["group_id"] == "987"


async def test_unified_msg_origin_passed_through() -> None:
    adapter = EventAdapter(sessions=None)

    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="2",
        display_name="d",
        unified_msg_origin="aiocqhttp:g:1",
        content="/番剧 本周",
    )

    assert reply is not None  # no crash when UMO is present


async def test_week_query_uses_schedule_builder_when_available() -> None:
    builder = ScheduleBuilder()
    adapter = EventAdapter(sessions=None, schedule_reply_builder=builder)
    ctx = ChatContext(
        platform="qq",
        group_id="1",
        user_id="2",
        display_name="d",
        unified_msg_origin=None,
        timezone=ZoneInfo("Asia/Shanghai"),
    )
    result = QueryResult(
        kind=IntentKind.WEEK,
        rows=(
            SimpleNamespace(
                id="anime-1",
                display_title="测试番剧",
                air_date=None,
                air_at=None,
                episode_label="01",
            ),
        ),
    )

    reply = await adapter._present_query(result, ctx=ctx)  # type: ignore[arg-type]

    assert builder.called
    assert reply.kind == "image"
