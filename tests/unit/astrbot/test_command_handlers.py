"""Unit tests for command handlers (Task 9)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from astrbot_plugin_anime_tracking.anime_tracking_plugin.commands import (
    CommandHandlers,
)
from astrbot_plugin_anime_tracking.anime_tracking_plugin.lifecycle import (
    PluginLifecycle,
)
from astrbot_plugin_anime_tracking.main import AnimeTrackingPlugin


@dataclass
class FakeSender:
    user_id: int = 111
    nickname: str = "alice"


@dataclass
class FakeEvent:
    message_str: str = ""
    group_id: int = 123456
    sender: FakeSender = field(default_factory=FakeSender)
    unified_msg_origin: str | None = "aiocqhttp:msg-1"


@pytest.mark.asyncio
async def test_handler_returns_rendered_text_for_valid_command() -> None:
    lifecycle = PluginLifecycle()
    handlers = CommandHandlers(lifecycle)
    event = FakeEvent(message_str="/番剧 本周")

    result = await handlers.on_fixed_command(event)

    assert isinstance(result, str)
    assert result  # non-empty reply


@pytest.mark.asyncio
async def test_handler_returns_error_for_unknown_command() -> None:
    lifecycle = PluginLifecycle()
    handlers = CommandHandlers(lifecycle)
    event = FakeEvent(message_str="/番剧 未知子命令")

    result = await handlers.on_fixed_command(event)

    assert isinstance(result, str)
    assert "错误" in result or "unknown" in result.lower()


@pytest.mark.asyncio
async def test_handler_returns_help_for_help_command() -> None:
    lifecycle = PluginLifecycle()
    handlers = CommandHandlers(lifecycle)
    event = FakeEvent(message_str="/番剧 帮助")

    result = await handlers.on_fixed_command(event)

    assert isinstance(result, str)
    assert "本周" in result


@pytest.mark.asyncio
async def test_empty_message_returns_none() -> None:
    lifecycle = PluginLifecycle()
    handlers = CommandHandlers(lifecycle)
    event = FakeEvent(message_str="")

    result = await handlers.on_fixed_command(event)

    assert result is None


def test_group_id_falls_back_to_message_object() -> None:
    event = SimpleNamespace(message_obj=SimpleNamespace(group_id=1091724800))

    assert AnimeTrackingPlugin._group_id(event) == "1091724800"
