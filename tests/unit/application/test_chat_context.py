"""Unit tests for the platform-neutral ChatContext (Task 6)."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from anime_qqbot.application import ChatContext


def test_default_context_carries_all_fields() -> None:
    ctx = ChatContext(
        platform="qq",
        group_id="123456",
        user_id="654321",
        display_name="alice",
        unified_msg_origin="aiocqhttp:123456",
        timezone=ZoneInfo("Asia/Shanghai"),
        is_admin=False,
    )

    assert ctx.platform == "qq"
    assert ctx.group_id == "123456"
    assert ctx.user_id == "654321"
    assert ctx.display_name == "alice"
    assert ctx.unified_msg_origin == "aiocqhttp:123456"
    assert ctx.timezone == ZoneInfo("Asia/Shanghai")
    assert ctx.is_admin is False


def test_context_admin_flag_default_false() -> None:
    ctx = ChatContext(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="x",
        unified_msg_origin=None,
        timezone=ZoneInfo("UTC"),
    )

    assert ctx.is_admin is False


def test_context_can_carry_no_umo() -> None:
    ctx = ChatContext(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="x",
        unified_msg_origin=None,
        timezone=ZoneInfo("Asia/Shanghai"),
    )

    assert ctx.unified_msg_origin is None


def test_with_timezone_helper_returns_zone_info() -> None:
    assert ChatContext.with_timezone("Asia/Shanghai") == ZoneInfo("Asia/Shanghai")
    assert ChatContext.with_timezone("UTC") == ZoneInfo("UTC")
