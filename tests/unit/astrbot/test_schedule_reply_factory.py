from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

from anime_qqbot.application.context import ChatContext
from anime_qqbot.presentation.renderer import RenderResult
from anime_qqbot.presentation.subscription_presentation import SubscriptionPresentation
from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import Reply
from astrbot_plugin_anime_tracking.anime_tracking_plugin.schedule_reply_factory import (
    ScheduleReplyFactory,
)


class Renderer:
    def __init__(self, result: RenderResult) -> None:
        self.result = result
        self.kwargs: dict[str, object] | None = None
        self.rows = None

    async def render_weekly_cached(self, rows, **kwargs):
        self.rows = tuple(rows)
        self.kwargs = kwargs
        return self.result

    async def render_daily_cached(self, rows, **kwargs):
        self.rows = tuple(rows)
        self.kwargs = kwargs
        return self.result


class SubscriptionReader:
    def __init__(self, presentation: SubscriptionPresentation | Exception) -> None:
        self.presentation = presentation

    async def read(self, **kwargs) -> SubscriptionPresentation:
        if isinstance(self.presentation, Exception):
            raise self.presentation
        return self.presentation


def subscriptions() -> SubscriptionPresentation:
    return SubscriptionPresentation(
        group_scope="group-scope",
        viewer_scope=None,
        viewer_follows=False,
        group_follow_counts={},
    )


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
        id=UUID("00000000-0000-0000-0000-000000000001"),
        display_title="测试番剧",
        air_date=date(2026, 8, 3),
        air_at=datetime(2026, 8, 3, 10, tzinfo=UTC),
        episode_label="01",
    )


async def test_success_returns_one_image_without_extra_text(tmp_path: Path) -> None:
    image = tmp_path / "weekly.png"
    image.touch()
    renderer = Renderer(RenderResult(image))
    factory = ScheduleReplyFactory(
        renderer=renderer,
        subscription_reader=SubscriptionReader(subscriptions()),  # type: ignore[arg-type]
    )

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
        "week_start": date(2026, 8, 2),
        "week_end": date(2026, 8, 8),
        "cache_scope": "group-scope",
    }


async def test_failed_render_returns_text_fallback() -> None:
    renderer = Renderer(RenderResult(None, "render_failed"))
    factory = ScheduleReplyFactory(
        renderer=renderer,
        subscription_reader=SubscriptionReader(subscriptions()),  # type: ignore[arg-type]
    )
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
    factory = ScheduleReplyFactory(
        renderer=renderer,
        subscription_reader=SubscriptionReader(subscriptions()),  # type: ignore[arg-type]
    )
    fallback = Reply.from_text("empty")

    reply = await factory.build_weekly(
        rows=(),
        ctx=context(),
        fallback=fallback,
        now=datetime(2026, 8, 5, 12, tzinfo=UTC),
    )

    assert reply is fallback
    assert renderer.kwargs is None


async def test_today_success_returns_one_image_with_requested_date(tmp_path: Path) -> None:
    image = tmp_path / "today.png"
    image.touch()
    renderer = Renderer(RenderResult(image))
    factory = ScheduleReplyFactory(
        renderer=renderer,
        subscription_reader=SubscriptionReader(subscriptions()),  # type: ignore[arg-type]
    )

    reply = await factory.build_today(
        rows=(row(),),
        ctx=context(),
        fallback=Reply.from_text("fallback"),
        target_date=date(2026, 8, 3),
    )

    assert reply.kind == "image"
    assert reply.blocks == [type(reply.blocks[0])(image_path=image)]
    assert renderer.kwargs == {
        "timezone": ZoneInfo("Asia/Shanghai"),
        "target_date": date(2026, 8, 3),
        "cache_scope": "group-scope",
    }


async def test_today_failed_render_returns_text_fallback() -> None:
    renderer = Renderer(RenderResult(None, "render_failed"))
    factory = ScheduleReplyFactory(
        renderer=renderer,
        subscription_reader=SubscriptionReader(subscriptions()),  # type: ignore[arg-type]
    )
    fallback = Reply.from_text("fallback")

    reply = await factory.build_today(
        rows=(row(),),
        ctx=context(),
        fallback=fallback,
        target_date=date(2026, 8, 3),
    )

    assert reply is fallback


async def test_adds_group_follow_count_without_exposing_viewer_state(tmp_path: Path) -> None:
    image = tmp_path / "weekly.png"
    image.touch()
    renderer = Renderer(RenderResult(image))
    source = row()
    factory = ScheduleReplyFactory(
        renderer=renderer,
        subscription_reader=SubscriptionReader(
            SubscriptionPresentation(
                group_scope="group-scope",
                viewer_scope=None,
                viewer_follows=False,
                group_follow_counts={source.id: 4},
            )
        ),  # type: ignore[arg-type]
    )

    reply = await factory.build_weekly(
        rows=(source,),
        ctx=context(),
        fallback=Reply.from_text("fallback"),
        now=datetime(2026, 8, 5, 12, tzinfo=UTC),
    )

    assert reply.kind == "image"
    assert renderer.rows is not None
    assert renderer.rows[0].group_follow_count == 4
