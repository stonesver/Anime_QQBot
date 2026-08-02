from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from anime_qqbot.application.context import ChatContext
from anime_qqbot.presentation.renderer import RenderResult
from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import Reply
from astrbot_plugin_anime_tracking.anime_tracking_plugin.schedule_reply_factory import (
    ScheduleReplyFactory,
)


class Renderer:
    def __init__(self, result: RenderResult) -> None:
        self.result = result
        self.kwargs: dict[str, object] | None = None

    async def render_cached(self, rows, **kwargs):
        self.kwargs = kwargs
        return self.result


def context() -> ChatContext:
    return ChatContext(
        platform="qq",
        group_id="group",
        user_id="user",
        display_name="alice",
        unified_msg_origin=None,
        timezone=ZoneInfo("Asia/Shanghai"),
    )


def row() -> SimpleNamespace:
    return SimpleNamespace(
        display_title="测试番剧",
        air_date=date(2026, 8, 3),
        air_at=datetime(2026, 8, 3, 10, tzinfo=UTC),
        episode_label="01",
    )


async def test_success_returns_one_image_without_extra_text(tmp_path: Path) -> None:
    image = tmp_path / "weekly.png"
    image.touch()
    renderer = Renderer(RenderResult(image))
    factory = ScheduleReplyFactory(renderer=renderer)  # type: ignore[arg-type]

    reply = await factory.build_weekly(
        rows=(row(),),
        ctx=context(),
        fallback=Reply.from_text("fallback"),
        now=datetime(2026, 8, 5, 12, tzinfo=UTC),
    )

    assert reply.kind == "image"
    assert reply.blocks == [type(reply.blocks[0])(image_path=image)]
    assert renderer.kwargs == {
        "timezone": ZoneInfo("Asia/Shanghai"),
        "week_start": date(2026, 8, 3),
        "week_end": date(2026, 8, 9),
    }


async def test_failed_render_returns_text_fallback() -> None:
    renderer = Renderer(RenderResult(None, "render_failed"))
    factory = ScheduleReplyFactory(renderer=renderer)  # type: ignore[arg-type]
    fallback = Reply.from_text("fallback")

    reply = await factory.build_weekly(
        rows=(row(),),
        ctx=context(),
        fallback=fallback,
        now=datetime(2026, 8, 5, 12, tzinfo=UTC),
    )

    assert reply is fallback


async def test_empty_rows_return_text_fallback_without_renderer_call() -> None:
    renderer = Renderer(RenderResult(None, "should_not_run"))
    factory = ScheduleReplyFactory(renderer=renderer)  # type: ignore[arg-type]
    fallback = Reply.from_text("empty")

    reply = await factory.build_weekly(
        rows=(),
        ctx=context(),
        fallback=fallback,
        now=datetime(2026, 8, 5, 12, tzinfo=UTC),
    )

    assert reply is fallback
    assert renderer.kwargs is None
