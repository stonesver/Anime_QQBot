"""AstrBot plugin: anime_tracking (v0.2.0).

This plugin bridges NapCat (OneBot 11) group events to the Anime Core
application layer. It follows the AstrBot Star plugin contract:

* The plugin class extends ``Star`` and is instantiated by the runtime.
* ``/番剧 <子命令>`` commands are registered via ``@filter.command_group``
  or ``@filter.command`` decorators.
* Replies are sent via ``yield event.plain_result(...)``.
* Cleanup goes through ``terminate()`` which stops the outbox dispatcher
  and disposes the database engine.

AstrBot SDK imports are guarded so the module compiles without the
SDK installed. At runtime the SDK must be present (it is provisioned
by AstrBot's Docker image).
"""

from __future__ import annotations

from typing import Any

# Guard AstrBot SDK imports for offline compilation.
try:
    from astrbot.api.event import (  # type: ignore[import-not-found]
        AstrMessageEvent,
        MessageEventResult,
        filter,  # noqa: A004
    )
    from astrbot.api.star import Context, Star  # type: ignore[import-not-found]
except ModuleNotFoundError:
    Star = object  # type: ignore[misc]
    Context = Any  # type: ignore[misc]
    AstrMessageEvent = Any  # type: ignore[misc]
    MessageEventResult = Any  # type: ignore[misc]

    class _FakeFilter:
        @staticmethod
        def command(_name: str) -> Any:
            return lambda fn: fn

        @staticmethod
        def command_group(_name: str) -> _FakeGroup:
            return _FakeGroup()

        @staticmethod
        def on_astrbot_loaded() -> Any:
            return lambda fn: fn

    class _FakeGroup:
        def __call__(self, fn: Any) -> Any:
            return self

        def command(self, _name: str) -> Any:
            return lambda fn: fn

    filter = _FakeFilter()  # type: ignore[misc]  # noqa: A001


from .anime_tracking_plugin.adapter import EventAdapter
from .anime_tracking_plugin.lifecycle import PluginLifecycle


class AnimeTrackingPlugin(Star):  # type: ignore[name-defined]
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._lifecycle: PluginLifecycle | None = None

    async def _ensure_lifecycle(self) -> PluginLifecycle:
        if self._lifecycle is None:
            self._lifecycle = PluginLifecycle(self.context)
            await self._lifecycle.start()
        return self._lifecycle

    @filter.on_astrbot_loaded()  # type: ignore[misc]
    async def _on_astrbot_loaded(self) -> None:
        """Start the durable notification consumer when AstrBot is ready."""
        await self._ensure_lifecycle()

    # ------------------------------------------------------------------
    # Fixed commands — 12 spec commands plus help
    # ------------------------------------------------------------------

    @filter.command_group("番剧")  # type: ignore[misc]
    async def _group_route(self, event: AstrMessageEvent) -> MessageEventResult:
        """All ``/番剧`` subcommands are registered on the parent group.

        Individual subcommand handlers receive ``event`` unchanged
        and delegate to the ``EventAdapter`` after extraction.
        """
        _ = event  # the group decorator keeps routes registered
        return

    @_group_route.command("帮助")  # type: ignore[union-attr]
    async def _handle_help(self, event: AstrMessageEvent) -> MessageEventResult:
        lifecycle = await self._ensure_lifecycle()
        adapter = self._build_adapter(lifecycle)
        reply = await adapter.handle_message(
            platform="qq",
            group_id=self._group_id(event),
            user_id=self._sender_id(event),
            display_name=self._sender_name(event),
            unified_msg_origin=self._umo(event),
            content=event.message_str,
        )
        if reply.blocks:
            yield event.plain_result(reply.blocks[0].text)
        elif reply.error:
            yield event.plain_result(f"错误: {reply.error}")

    @_group_route.command("今天")  # type: ignore[union-attr]
    async def _handle_today(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("本周")  # type: ignore[union-attr]
    async def _handle_week(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("季度")  # type: ignore[union-attr]
    async def _handle_season(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("搜索")  # type: ignore[union-attr]
    async def _handle_search(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("详情")  # type: ignore[union-attr]
    async def _handle_detail(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("下次")  # type: ignore[union-attr]
    async def _handle_next(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("订阅")  # type: ignore[union-attr]
    async def _handle_subscribe(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("取消订阅")  # type: ignore[union-attr]
    async def _handle_unsubscribe(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("我的订阅")  # type: ignore[union-attr]
    async def _handle_my(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("订阅设置")  # type: ignore[union-attr]
    async def _handle_settings(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("状态")  # type: ignore[union-attr]
    async def _handle_status(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    @_group_route.command("映射待处理")  # type: ignore[union-attr]
    async def _handle_mapping(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(await self._dispatch(event))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def terminate(self) -> None:
        if self._lifecycle is not None:
            await self._lifecycle.shutdown()
            self._lifecycle = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_adapter(self, lifecycle: PluginLifecycle) -> EventAdapter:
        return EventAdapter(sessions=lifecycle.sessions)

    async def _dispatch(self, event: AstrMessageEvent) -> str:
        lifecycle = await self._ensure_lifecycle()
        adapter = self._build_adapter(lifecycle)
        reply = await adapter.handle_message(
            platform="qq",
            group_id=self._group_id(event),
            user_id=self._sender_id(event),
            display_name=self._sender_name(event),
            unified_msg_origin=self._umo(event),
            content=event.message_str,
        )
        if reply.blocks:
            return reply.blocks[0].text
        if reply.candidates:
            return "多个结果, 请通过内部 ID 选择:\n" + "\n".join(reply.candidates)
        if reply.error:
            return f"错误: {reply.error}"
        return "（无内容）"

    @staticmethod
    def _group_id(event: Any) -> str:
        return str(getattr(event, "group_id", "") or "")

    @staticmethod
    def _sender_id(event: Any) -> str:
        sender = getattr(event, "get_sender_id", None)
        if callable(sender):
            return str(sender())
        return str(getattr(event, "sender", {}).get("user_id", ""))

    @staticmethod
    def _sender_name(event: Any) -> str:
        sender = getattr(event, "get_sender_name", None)
        if callable(sender):
            return str(sender())
        return str(getattr(event, "sender", {}).get("nickname", ""))

    @staticmethod
    def _umo(event: Any) -> str | None:
        return getattr(event, "unified_msg_origin", None)


__all__ = ["AnimeTrackingPlugin"]
