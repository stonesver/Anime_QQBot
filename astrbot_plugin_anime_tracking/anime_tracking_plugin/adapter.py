"""AstrBot event adapter (Task 9 + P0.4).

Converts AstrMessageEvent -> ChatContext -> Intent -> Anime Core
use case -> platform-neutral Reply that rendering.py maps to
AstrBot message components.

The adapter is intentionally thin: all real behaviour lives in
``anime_qqbot.application.use_cases``. The adapter's job is to
construct a ``ChatContext`` from an incoming event, dispatch the
parsed Intent to the right use case, and translate the result
into one of:

* ``kind='text'`` — single block of plain text
* ``kind='candidates'`` — list of ``<anime_id> <title>`` rows the
  user must disambiguate by typing the internal ID
* ``kind='error'`` — short error message that the renderer prefixes
  with ``解析失败: ``
* ``kind='help'`` — the fixed-command help block
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.application import (
    ChatContext,
    Intent,
    IntentKind,
    ParseFailure,
    QueryResult,
    ResourceDetailResult,
    SubscribeResult,
    detail_for,
    my_subscriptions,
    next_airing_for,
    parse_fixed_command,
    pending_mappings,
    resource_details,
    search_anime,
    season_listing,
    source_freshness,
    subscribe,
    subscription_settings,
    today_listing,
    unsubscribe,
    week_listing,
)
from anime_qqbot.interactions.models import CandidateItem, InteractionScope
from anime_qqbot.interactions.repository import InteractionSessionRepository
from anime_qqbot.presentation.models import CardScene
from anime_qqbot.presentation.text import format_listing
from anime_qqbot.resources.presentation import format_resource_detail

# ---------------------------------------------------------------------------
# Platform-neutral reply types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplyBlock:
    """One text or image segment of a reply."""

    text: str = ""
    image_path: Path | None = None


@dataclass
class Reply:
    kind: str = "text"
    blocks: list[ReplyBlock] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    candidate_items: list[CandidateItem] = field(default_factory=list)
    at_user_ids: list[str] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_text(cls, text: str) -> Reply:
        return cls(kind="text", blocks=[ReplyBlock(text=text)])

    @classmethod
    def from_candidates(cls, rows: tuple[Any, ...]) -> Reply:
        items = [
            CandidateItem(
                anime_id=row.id,
                title=row.display_title or "未命名番剧",
            )
            for row in rows
        ]
        return cls(
            kind="candidates",
            candidates=[item.title for item in items],
            candidate_items=items,
        )

    @classmethod
    def from_error(cls, message: str) -> Reply:
        return cls(kind="error", error=message)

    @classmethod
    def from_image(cls, image_path: Path, *, hint: str | None = None) -> Reply:
        blocks = [ReplyBlock(image_path=image_path)]
        if hint:
            blocks.append(ReplyBlock(text=hint))
        return cls(kind="image", blocks=blocks)


class CardReplyBuilder(Protocol):
    async def build(
        self,
        *,
        scene: CardScene,
        anime_id: UUID,
        ctx: ChatContext,
        fallback: Reply,
        now: datetime,
    ) -> Reply: ...


class ScheduleReplyBuilder(Protocol):
    async def build_weekly(
        self,
        *,
        rows: tuple[Any, ...],
        ctx: ChatContext,
        fallback: Reply,
        now: datetime,
    ) -> Reply: ...

    async def build_today(
        self,
        *,
        rows: tuple[Any, ...],
        ctx: ChatContext,
        fallback: Reply,
        target_date: date,
    ) -> Reply: ...


def help_reply() -> Reply:
    return Reply(
        kind="help",
        blocks=[
            ReplyBlock(
                text=(
                    "/番剧 今天 [YYYY-MM-DD]\n"
                    "/番剧 本周\n"
                    "/番剧 季度 [年份] [冬|春|夏|秋]\n"
                    "/番剧 搜索 <关键词>\n"
                    "/番剧 详情 <内部ID|关键词>\n"
                    "/番剧 资源详情 <关键词> [集数]\n"
                    "资源详情 <关键词> [集数]\n"
                    "/番剧 下次 <内部ID|关键词>\n"
                    "/番剧 订阅 <内部ID|关键词>\n"
                    "/番剧 取消订阅 <内部ID|关键词>\n"
                    "/番剧 我的订阅\n"
                    "/番剧 订阅设置 <内部ID> "
                    "[语言=简体|繁体|不限] [字幕组=A,B|不限] "
                    "[分辨率=1080p,720p|不限]\n"
                    "/番剧 状态\n"
                    "/番剧 映射待处理"
                )
            )
        ],
    )


# ---------------------------------------------------------------------------
# Use case handler type
# ---------------------------------------------------------------------------

UseCaseHandler = Callable[[ChatContext, Intent], Coroutine[Any, Any, Reply]]


def _format_anime_row(row: Any, timezone: ZoneInfo | None = None) -> str:
    title = row.display_title or str(row.id)
    flag = "🔞" if row.nsfw_flag == "true" else ""
    schedule = ""
    air_date = getattr(row, "air_date", None)
    air_at = getattr(row, "air_at", None)
    episode = getattr(row, "episode_label", None)
    if air_date is not None:
        weekday = "一二三四五六日"[air_date.weekday()]
        time_label = (
            air_at.astimezone(timezone or ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
            if air_at
            else "日期待定"
        )
        episode_label = f" · 第{episode}集" if episode else ""
        schedule = f"\n  周{weekday} {air_date:%m-%d} {time_label}{episode_label}"
    return f"• {title}{flag}{schedule}"


async def _query_to_reply(result: QueryResult, *, ctx: ChatContext) -> Reply:
    if result.kind == IntentKind.TODAY:
        if not result.rows:
            return Reply.from_text("今天没有即将放送的番剧")
        return Reply.from_text(
            format_listing(
                result.rows,
                title="📺 今日放送",
                timezone=ctx.timezone,
                footer="发送「搜番 名称」查看详情",
            )
        )
    if result.kind == IntentKind.WEEK:
        if not result.rows:
            return Reply.from_text("本周没有即将放送的番剧")
        return Reply.from_text(
            format_listing(
                result.rows,
                title="🗓 本周放送",
                timezone=ctx.timezone,
                footer="追番时发送「追番 名称」",
            )
        )
    if result.kind == IntentKind.SEASON:
        if not result.rows:
            return Reply.from_text("该季度没有已收录的番剧")
        return Reply.from_text(format_listing(result.rows, title="季度番剧", timezone=ctx.timezone))
    if result.kind == IntentKind.SEARCH:
        if result.detail is not None:
            title = result.detail.display_title or "该番剧"
            return Reply.from_text(
                f"{_format_anime_row(result.detail, ctx.timezone)}\n\n发送“追番 {title}”即可订阅。"
            )
        if result.candidates:
            return Reply.from_candidates(result.candidates)
        return Reply.from_text(result.message or "未找到匹配的番剧，请使用 /番剧 搜索 <关键词>")
    if result.kind == IntentKind.DETAIL:
        if result.blocked:
            return Reply.from_error("该番剧被屏蔽，不予展示")
        if result.detail is None:
            return Reply.from_text("找不到对应番剧")
        return Reply.from_text(
            f"番剧详情\n{_format_anime_row(result.detail, ctx.timezone)}\n\n"
            f"下一步：追番 {result.detail.display_title or ''}"
        )
    if result.kind == IntentKind.NEXT:
        if result.blocked:
            return Reply.from_error("该番剧被屏蔽，不予展示")
        if result.detail is None:
            return Reply.from_text("找不到对应番剧")
        label = result.message or "暂无下一集"
        return Reply.from_text(f"下一集: {label}\n{_format_anime_row(result.detail, ctx.timezone)}")
    if result.kind == IntentKind.MY_SUBSCRIPTIONS:
        if not result.rows:
            return Reply.from_text("你当前没有订阅")
        body = "\n".join(_format_anime_row(r, ctx.timezone) for r in result.rows)
        return Reply.from_text(f"我的订阅 ({len(result.rows)} 部)\n{body}")
    if result.kind == IntentKind.STATUS:
        return Reply.from_text(result.message or "暂无来源状态")
    if result.kind == IntentKind.MAPPING_PENDING:
        return Reply.from_text(result.message or "没有待处理映射")
    return Reply.from_error(f"unsupported query kind: {result.kind.value}")


async def _subscribe_to_reply(result: SubscribeResult) -> Reply:
    if not result.success:
        if result.informational:
            return Reply.from_text(result.detail_message)
        return Reply.from_error(result.detail_message)
    if result.anime is None:
        return Reply.from_text(result.detail_message)
    title = result.anime.display_title or str(result.anime.id)
    return Reply.from_text(f"{result.detail_message}\n{title}")


def _resource_detail_to_reply(result: ResourceDetailResult) -> Reply:
    if result.candidates:
        lines = ["匹配到多个番剧，请使用完整标题重新查询："]
        lines.extend(
            f"{index}. {row.display_title or '未命名番剧'}"
            for index, row in enumerate(result.candidates, start=1)
        )
        return Reply.from_text("\n".join(lines))
    if result.anime is None:
        return Reply.from_text("找不到对应番剧")
    title = result.anime.display_title or "该番剧"
    if not result.summaries:
        episode = f"第 {result.episode_label} 集" if result.episode_label is not None else "最近"
        return Reply.from_text(f"{title} 暂无{episode}资源")
    return Reply.from_text(
        format_resource_detail(
            display_title=title,
            episode_label=result.episode_label,
            summaries=result.summaries,
            page_url=result.page_url,
        )
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class EventAdapter:
    """Glue between AstrBot event and Anime Core use cases.

    The adapter requires an ``async_sessionmaker`` so it can call
    the real use cases. The AstrBot plugin constructs this adapter
    inside ``PluginLifecycle.start()`` so the database is always
    available before any message is dispatched.
    """

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession] | None,
        handlers: dict[IntentKind, UseCaseHandler] | None = None,
        card_reply_builder: CardReplyBuilder | None = None,
        schedule_reply_builder: ScheduleReplyBuilder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._card_reply_builder = card_reply_builder
        self._schedule_reply_builder = schedule_reply_builder
        self._clock = clock or _now
        self._handlers = handlers or self._default_handlers()

    async def _present_query(
        self,
        result: QueryResult,
        *,
        ctx: ChatContext,
        now: datetime | None = None,
        target_date: date | None = None,
    ) -> Reply:
        fallback = await _query_to_reply(result, ctx=ctx)
        if result.kind == IntentKind.WEEK and self._schedule_reply_builder is not None:
            return await self._schedule_reply_builder.build_weekly(
                rows=result.rows,
                ctx=ctx,
                fallback=fallback,
                now=now or self._clock(),
            )
        if (
            result.kind == IntentKind.TODAY
            and self._schedule_reply_builder is not None
            and target_date is not None
        ):
            return await self._schedule_reply_builder.build_today(
                rows=result.rows,
                ctx=ctx,
                fallback=fallback,
                target_date=target_date,
            )
        if self._card_reply_builder is None or result.detail is None:
            return fallback
        scene = {
            IntentKind.SEARCH: CardScene.UNIQUE_SEARCH,
            IntentKind.DETAIL: CardScene.DETAIL,
            IntentKind.NEXT: CardScene.NEXT,
        }.get(result.kind)
        if scene is None:
            return fallback
        return await self._card_reply_builder.build(
            scene=scene,
            anime_id=result.detail.id,
            ctx=ctx,
            fallback=fallback,
            now=self._clock(),
        )

    async def handle_message(
        self,
        *,
        platform: str,
        group_id: str,
        user_id: str,
        display_name: str,
        unified_msg_origin: str | None,
        content: str,
        is_admin: bool = False,
        timezone_name: str = "Asia/Shanghai",
        now: datetime | None = None,
    ) -> Reply:
        if platform == "qq" and (not group_id.strip() or not user_id.strip()):
            return Reply.from_error("无法识别当前群或用户，未执行操作")

        ctx = ChatContext(
            platform=platform,
            group_id=group_id,
            user_id=user_id,
            display_name=display_name,
            unified_msg_origin=unified_msg_origin,
            timezone=ZoneInfo(timezone_name),
            is_admin=is_admin,
        )

        # Every valid group event upserts the chat_group row and
        # refreshes the membership. This keeps the UMO cache fresh
        # so the outbox dispatcher can find a target to send to.
        if platform == "qq" and self._sessions is not None:
            await self._record_group_event(
                platform, group_id, user_id, display_name, unified_msg_origin
            )

        result = parse_fixed_command(content)
        if isinstance(result, ParseFailure):
            return Reply.from_error(result.reason)

        intent = result
        reply = await self.handle_intent(ctx=ctx, intent=intent, now=now)
        if reply.candidate_items:
            await self.persist_candidates(
                ctx=ctx,
                reply=reply,
                now=now or _now(),
            )
        return reply

    async def handle_intent(
        self,
        *,
        ctx: ChatContext,
        intent: Intent,
        now: datetime | None = None,
    ) -> Reply:
        if intent.kind == IntentKind.HELP:
            return help_reply()

        if intent.selection_number is not None:
            resolved = await self._resolve_selection(ctx, intent, now=now)
            if isinstance(resolved, Reply):
                return resolved
            intent = resolved

        handler = self._handlers.get(intent.kind)
        if handler is None:
            return Reply.from_error(f"unknown intent: {intent.kind.value}")
        return await handler(ctx, intent)

    async def persist_candidates(
        self,
        *,
        ctx: ChatContext,
        reply: Reply,
        now: datetime,
        result_message_id: str | None = None,
    ) -> None:
        if not reply.candidate_items:
            return
        if self._sessions is None:
            return
        await InteractionSessionRepository(self._sessions).replace(
            InteractionScope(ctx.platform, ctx.group_id, ctx.user_id),
            reply.candidate_items,
            now=now,
            result_message_id=result_message_id,
        )

    async def _resolve_selection(
        self,
        ctx: ChatContext,
        intent: Intent,
        *,
        now: datetime | None,
    ) -> Intent | Reply:
        if self._sessions is None:
            return Reply.from_error("数据库未配置")
        session = await InteractionSessionRepository(self._sessions).resolve(
            InteractionScope(ctx.platform, ctx.group_id, ctx.user_id),
            now=now or _now(),
        )
        if session is None:
            return Reply.from_error("候选结果已过期，请重新搜番")
        candidate = session.candidate(intent.selection_number or 0)
        if candidate is None:
            return Reply.from_error("编号不在当前候选范围内")
        return replace(
            intent,
            anime_id=str(candidate.anime_id),
            query=None,
            selection_number=None,
        )

    async def _record_group_event(
        self,
        platform: str,
        group_id: str,
        user_id: str,
        display_name: str,
        unified_msg_origin: str | None,
    ) -> None:
        from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent

        if self._sessions is None:
            return
        repo = ChatGroupRepository(self._sessions)
        await repo.upsert_group_event(
            GroupEvent(
                platform=platform,
                external_group_id=group_id,
                external_user_id=user_id,
                display_name=display_name,
                unified_msg_origin=unified_msg_origin,
                timestamp=datetime.now(UTC),
            )
        )

    def _default_handlers(self) -> dict[IntentKind, UseCaseHandler]:
        s = self._sessions

        async def _no_db() -> Reply:
            return Reply.from_error("数据库未配置")

        async def _today(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            if intent.query:
                target_date = date.fromisoformat(intent.query)
            else:
                target_date = self._clock().astimezone(ctx.timezone).date()
            return await self._present_query(
                await today_listing(
                    s,
                    target_date=target_date,
                    timezone=ctx.timezone,
                ),
                ctx=ctx,
                target_date=target_date,
            )

        async def _week(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            now = self._clock()
            return await self._present_query(
                await week_listing(
                    s,
                    now=now,
                    timezone=ctx.timezone,
                ),
                ctx=ctx,
                now=now,
            )

        async def _search(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await self._present_query(
                await search_anime(s, query=intent.query or ""),
                ctx=ctx,
            )

        async def _season(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            now = self._clock()
            return await self._present_query(
                await season_listing(
                    s,
                    year=intent.season_year or now.year,
                    season_name=intent.season_name or "冬",
                ),
                ctx=ctx,
            )

        async def _detail(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await self._present_query(
                await detail_for(s, anime_id=intent.anime_id, query=intent.query),
                ctx=ctx,
            )

        async def _next(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await self._present_query(
                await next_airing_for(
                    s,
                    anime_id=intent.anime_id,
                    query=intent.query,
                    now=self._clock(),
                ),
                ctx=ctx,
            )

        async def _resource_detail(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return _resource_detail_to_reply(
                await resource_details(
                    s,
                    anime_id=intent.anime_id,
                    query=intent.query,
                    episode_label=intent.episode_label,
                )
            )

        async def _my(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await self._present_query(await my_subscriptions(s, ctx=ctx), ctx=ctx)

        async def _subscribe(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await _subscribe_to_reply(await subscribe(s, ctx=ctx, intent=intent))

        async def _unsubscribe(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await _subscribe_to_reply(await unsubscribe(s, ctx=ctx, intent=intent))

        async def _settings(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await _subscribe_to_reply(await subscription_settings(s, ctx=ctx, intent=intent))

        async def _status(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await self._present_query(await source_freshness(s), ctx=ctx)

        async def _mapping(ctx: ChatContext, intent: Intent) -> Reply:
            if s is None:
                return await _no_db()
            return await self._present_query(await pending_mappings(s), ctx=ctx)

        return {
            IntentKind.TODAY: _today,
            IntentKind.WEEK: _week,
            IntentKind.SEASON: _season,
            IntentKind.SEARCH: _search,
            IntentKind.DETAIL: _detail,
            IntentKind.RESOURCE_DETAIL: _resource_detail,
            IntentKind.NEXT: _next,
            IntentKind.MY_SUBSCRIPTIONS: _my,
            IntentKind.SUBSCRIBE: _subscribe,
            IntentKind.UNSUBSCRIBE: _unsubscribe,
            IntentKind.SUBSCRIPTION_SETTINGS: _settings,
            IntentKind.STATUS: _status,
            IntentKind.MAPPING_PENDING: _mapping,
        }


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "CardReplyBuilder",
    "EventAdapter",
    "Reply",
    "ReplyBlock",
    "ScheduleReplyBuilder",
    "UseCaseHandler",
    "help_reply",
]


_ = (UUID,)
