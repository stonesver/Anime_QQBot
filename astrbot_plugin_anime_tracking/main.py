"""AstrBot plugin: anime_tracking (v0.4.0).

This plugin bridges NapCat (OneBot 11) group events to the Anime Core
application layer. It follows the AstrBot Star plugin contract:

* The plugin class extends ``Star`` and is instantiated by the runtime.
* ``/番剧 <子命令>`` commands are registered via ``@filter.command_group``
  or ``@filter.command`` decorators.
* Replies are sent through one local Plain / Image message-chain boundary.
* Cleanup goes through ``terminate()`` which stops the outbox dispatcher
  and disposes the database engine.

AstrBot SDK imports are guarded so the module compiles without the
SDK installed. At runtime the SDK must be present (it is provisioned
by AstrBot's Docker image).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Guard AstrBot SDK imports for offline compilation.
try:
    from astrbot.api.event import (  # type: ignore[import-not-found]
        AstrMessageEvent,
        MessageEventResult,
        filter,  # noqa: A004
    )
    from astrbot.api.provider import LLMResponse, ProviderRequest  # type: ignore[import-not-found]
    from astrbot.api.star import Context, Star  # type: ignore[import-not-found]
    from astrbot.core.agent.message import TextPart  # type: ignore[import-not-found]
    from astrbot.core.agent.run_context import ContextWrapper  # type: ignore[import-not-found]
    from astrbot.core.astr_agent_context import AstrAgentContext  # type: ignore[import-not-found]
except ModuleNotFoundError:
    Context = Any  # type: ignore[misc]
    AstrMessageEvent = Any  # type: ignore[misc]
    MessageEventResult = Any  # type: ignore[misc]
    ProviderRequest = Any  # type: ignore[misc]
    LLMResponse = Any  # type: ignore[misc]
    ContextWrapper = Any  # type: ignore[misc]
    AstrAgentContext = Any  # type: ignore[misc]

    class Star:  # type: ignore[no-redef]
        def __init__(self, context: Any) -> None:
            self.context = context

    class TextPart:  # type: ignore[no-redef]
        def __init__(self, *, text: str) -> None:
            self.text = text

        def mark_as_temp(self) -> TextPart:
            return self

    class _FakeFilter:
        class EventMessageType:
            GROUP_MESSAGE = "group_message"

        @staticmethod
        def command(_name: str) -> Any:
            return lambda fn: fn

        @staticmethod
        def command_group(_name: str) -> _FakeGroup:
            return _FakeGroup()

        @staticmethod
        def on_astrbot_loaded() -> Any:
            return lambda fn: fn

        @staticmethod
        def event_message_type(_kind: Any) -> Any:
            return lambda fn: fn

        @staticmethod
        def on_llm_request() -> Any:
            return lambda fn: fn

        @staticmethod
        def on_agent_done() -> Any:
            return lambda fn: fn

    class _FakeGroup:
        def __call__(self, fn: Any) -> Any:
            return self

        def command(self, _name: str) -> Any:
            return lambda fn: fn

    filter = _FakeFilter()  # type: ignore[misc]  # noqa: A001


from anime_qqbot.content_operations.polls import PollService, format_poll
from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent
from anime_qqbot.groups.settings import GroupRuntimeSettingsRepository
from anime_qqbot.notifications.governor import DeliveryClass, SendRequest

from .anime_tracking_plugin.adapter import EventAdapter, Reply
from .anime_tracking_plugin.admin_api import AdminWebAPI
from .anime_tracking_plugin.astrbot_tool import AnimeReadonlyTool
from .anime_tracking_plugin.event_envelope import (
    from_astrbot_event,
    group_id_from_astrbot_event,
)
from .anime_tracking_plugin.interaction_gateway import InteractionGateway
from .anime_tracking_plugin.lifecycle import PluginLifecycle
from .anime_tracking_plugin.llm_policy import LLMPolicyGuard, runtime_hint
from .anime_tracking_plugin.rendering import reply_to_event_result


class AnimeTrackingPlugin(Star):  # type: ignore[name-defined]
    def __init__(self, context: Context, config: dict[str, Any] | None = None) -> None:
        super().__init__(context)
        self._config = config or {}
        self._lifecycle: PluginLifecycle | None = None
        self._llm_policy_guard = LLMPolicyGuard()
        self._readonly_tool = AnimeReadonlyTool(
            lifecycle_provider=self._ensure_lifecycle,
            policy_guard=self._llm_policy_guard,
        )
        self.context.add_llm_tools(self._readonly_tool)
        self._admin_api = AdminWebAPI(context, self._ensure_lifecycle)

    async def _ensure_lifecycle(self) -> PluginLifecycle:
        if self._lifecycle is None:
            self._lifecycle = PluginLifecycle(self.context, config=self._config)
            await self._lifecycle.start()
        return self._lifecycle

    @filter.on_astrbot_loaded()  # type: ignore[misc]
    async def _on_astrbot_loaded(self) -> None:
        """Start the durable notification consumer when AstrBot is ready."""
        await self._ensure_lifecycle()

    @filter.on_llm_request()  # type: ignore[misc]
    async def _on_llm_request(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
    ) -> None:
        """Inject one-turn policy only for explicit QQ group mentions."""
        envelope = from_astrbot_event(event)
        if not envelope.group_id or not envelope.user_id or not envelope.mentions_bot:
            return
        try:
            general_chat_enabled = await self._general_chat_enabled(event)
        except Exception:
            general_chat_enabled = False
        self._llm_policy_guard.begin(
            event,
            general_chat_enabled=general_chat_enabled,
        )
        req.extra_user_content_parts.append(
            TextPart(text=runtime_hint(general_chat_enabled=general_chat_enabled)).mark_as_temp()
        )

    @filter.on_agent_done()  # type: ignore[misc]
    async def _on_agent_done(
        self,
        event: AstrMessageEvent,
        run_context: ContextWrapper[AstrAgentContext],
        resp: LLMResponse,
    ) -> None:
        """Replace ungrounded or failed completions before AstrBot sends them."""
        _ = run_context
        resp.completion_text = self._llm_policy_guard.finish(
            event,
            str(getattr(resp, "completion_text", "")),
        )

    # ------------------------------------------------------------------
    # Fixed commands — 12 spec commands plus help
    # ------------------------------------------------------------------

    @filter.command_group("番剧")  # type: ignore[misc]
    async def _group_route(self, event: AstrMessageEvent) -> MessageEventResult:
        """All ``/番剧`` subcommands are registered on the parent group.

        Individual subcommand handlers receive ``event`` unchanged
        and delegate to the ``EventAdapter`` after extraction.
        """
        yield event.plain_result(
            "可用入口：今日番剧、本周番剧、搜番 <关键词>、追番 <关键词>、"
            "退订 <关键词>、我的追番。完整命令请发送 /番剧 帮助"
        )

    @filter.event_message_type(  # type: ignore[misc]
        filter.EventMessageType.GROUP_MESSAGE  # type: ignore[attr-defined]
    )
    async def _handle_group_message(self, event: AstrMessageEvent) -> MessageEventResult:
        """Handle @ and explicitly enabled direct shortcuts.

        Slash commands remain owned by the command-group decorators so one
        incoming message can never receive duplicate replies.
        """
        message = str(getattr(event, "message_str", "")).strip()
        if message.startswith("/番剧") or message.startswith("资源详情"):
            return
        lifecycle = await self._ensure_lifecycle()
        result = await InteractionGateway(lifecycle).route(from_astrbot_event(event))
        if not result.matched:
            return
        if result.stop_propagation:
            stopper = getattr(event, "stop_event", None)
            if callable(stopper):
                stopper()
        if result.reply is not None:
            yield self._reply_result(event, result.reply)
        elif result.text:
            yield self._reply_result(event, Reply.from_text(result.text))

    @_group_route.command("帮助")  # type: ignore[union-attr]
    async def _handle_help(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("今天")  # type: ignore[union-attr]
    async def _handle_today(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("本周")  # type: ignore[union-attr]
    async def _handle_week(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("季度")  # type: ignore[union-attr]
    async def _handle_season(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("搜索")  # type: ignore[union-attr]
    async def _handle_search(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("详情")  # type: ignore[union-attr]
    async def _handle_detail(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("资源详情")  # type: ignore[union-attr]
    async def _handle_resource_detail(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @filter.command("资源详情")  # type: ignore[misc]
    async def _handle_resource_detail_direct(
        self,
        event: AstrMessageEvent,
    ) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("下次")  # type: ignore[union-attr]
    async def _handle_next(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("订阅")  # type: ignore[union-attr]
    async def _handle_subscribe(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("取消订阅")  # type: ignore[union-attr]
    async def _handle_unsubscribe(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("我的订阅")  # type: ignore[union-attr]
    async def _handle_my(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("订阅设置")  # type: ignore[union-attr]
    async def _handle_settings(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("状态")  # type: ignore[union-attr]
    async def _handle_status(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("映射待处理")  # type: ignore[union-attr]
    async def _handle_mapping(self, event: AstrMessageEvent) -> MessageEventResult:
        yield await self._dispatch_result(event)

    @_group_route.command("投票")  # type: ignore[union-attr]
    async def _handle_poll(self, event: AstrMessageEvent) -> MessageEventResult:
        lifecycle = await self._ensure_lifecycle()
        cooldown = self._interactive_cooldown(event, lifecycle)
        if cooldown is not None:
            yield event.plain_result(cooldown)
            return
        if lifecycle.sessions is None:
            yield event.plain_result("投票服务暂不可用。")
            return
        polls = PollService(lifecycle.sessions)
        parts = str(getattr(event, "message_str", "")).strip().split()
        try:
            position = next(
                (int(value) for value in reversed(parts) if value.isdigit()),
                None,
            )
            if position is None:
                current = await polls.current(
                    external_group_id=self._group_id(event),
                    now=datetime.now(UTC),
                )
                text = format_poll(current) if current is not None else "当前没有进行中的番剧投票。"
            else:
                result = await polls.vote(
                    external_group_id=self._group_id(event),
                    external_user_id=self._sender_id(event),
                    position=position,
                    now=datetime.now(UTC),
                )
                text = (
                    f"已投给 {result.poll.candidates[position - 1].title}。\n"
                    f"当前票数：{result.counts[position]}"
                )
        except (ValueError, IndexError):
            text = "投票失败：请确认当前有进行中的投票，并发送 /番剧 投票 <编号>。"
        yield event.plain_result(text)

    @_group_route.command("取消投票")  # type: ignore[union-attr]
    async def _handle_cancel_poll(self, event: AstrMessageEvent) -> MessageEventResult:
        lifecycle = await self._ensure_lifecycle()
        cooldown = self._interactive_cooldown(event, lifecycle)
        if cooldown is not None:
            yield event.plain_result(cooldown)
            return
        if lifecycle.sessions is None:
            yield event.plain_result("投票服务暂不可用。")
            return
        try:
            removed = await PollService(lifecycle.sessions).cancel_vote(
                external_group_id=self._group_id(event),
                external_user_id=self._sender_id(event),
                now=datetime.now(UTC),
            )
            text = "已取消你的投票。" if removed else "你还没有参与当前投票。"
        except ValueError:
            text = "当前没有进行中的番剧投票。"
        yield event.plain_result(text)

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
        return EventAdapter(
            sessions=lifecycle.sessions,
            card_reply_builder=lifecycle.card_reply_factory,
            schedule_reply_builder=lifecycle.schedule_reply_factory,
        )

    async def _general_chat_enabled(self, event: AstrMessageEvent) -> bool:
        lifecycle = await self._ensure_lifecycle()
        if lifecycle.sessions is None:
            return False
        envelope = from_astrbot_event(event)
        group = await ChatGroupRepository(lifecycle.sessions).upsert_group_event(
            GroupEvent(
                platform=envelope.platform,
                external_group_id=envelope.group_id,
                external_user_id=envelope.user_id,
                display_name=envelope.display_name,
                unified_msg_origin=envelope.unified_msg_origin,
                timestamp=datetime.now(UTC),
            )
        )
        policy = await GroupRuntimeSettingsRepository(lifecycle.sessions).get_policy(group.id)
        return policy.general_chat_enabled

    def _interactive_cooldown(
        self, event: AstrMessageEvent, lifecycle: PluginLifecycle
    ) -> str | None:
        if not bool(self._config.get("send_governor_enabled", False)):
            return None
        permit = lifecycle.governor.acquire(
            SendRequest(
                DeliveryClass.INTERACTIVE,
                self._group_id(event),
                self._sender_id(event),
            )
        )
        if permit.allowed:
            return None
        return f"请求有点快，请 {max(1, round(permit.retry_after_seconds))} 秒后再试。"

    async def _dispatch_result(self, event: AstrMessageEvent) -> Any:
        return self._reply_result(event, await self._dispatch(event))

    async def _dispatch(self, event: AstrMessageEvent) -> Reply:
        lifecycle = await self._ensure_lifecycle()
        cooldown = self._interactive_cooldown(event, lifecycle)
        if cooldown is not None:
            return Reply.from_text(cooldown)
        adapter = self._build_adapter(lifecycle)
        reply = await adapter.handle_message(
            platform="qq",
            group_id=self._group_id(event),
            user_id=self._sender_id(event),
            display_name=self._sender_name(event),
            unified_msg_origin=self._umo(event),
            content=event.message_str,
            is_admin=getattr(event, "role", "member") == "admin",
        )
        return reply

    @staticmethod
    def _reply_result(event: Any, reply: Reply) -> Any:
        asset_root = Path(os.environ.get("CARD_ASSET_ROOT", "/var/lib/anime-qqbot/cards"))
        return reply_to_event_result(event, reply, asset_root=asset_root)

    @staticmethod
    def _group_id(event: Any) -> str:
        return group_id_from_astrbot_event(event)

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
