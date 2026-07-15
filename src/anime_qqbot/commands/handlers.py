# ruff: noqa: RUF001

from datetime import date
from zoneinfo import ZoneInfo

from anime_qqbot.catalog.models import AnimeDetail, Season, SeasonName
from anime_qqbot.catalog.module import AnimeCatalog
from anime_qqbot.clock import Clock
from anime_qqbot.commands.models import CommandIntent, CommandKind
from anime_qqbot.commands.router import CommandRouter
from anime_qqbot.qq.contracts import OutboundMessage, QQEvent
from anime_qqbot.qq.gateway import QQGateway
from anime_qqbot.qq.rendering import (
    HELP_TEXT,
    render_detail,
    render_listing,
    render_next,
    render_search,
)
from anime_qqbot.subscriptions.module import SubscriptionManager


class CommandHandler:
    def __init__(
        self,
        router: CommandRouter,
        catalog: AnimeCatalog,
        subscriptions: SubscriptionManager,
        gateway: QQGateway,
        clock: Clock,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self._router = router
        self._catalog = catalog
        self._subscriptions = subscriptions
        self._gateway = gateway
        self._clock = clock
        self._timezone = ZoneInfo(timezone)

    async def handle(self, event: QQEvent) -> None:
        intent = await self._router.route(event)
        if intent is None:
            return
        if not intent.valid:
            await self._reply(event, intent.error or "参数错误")
            return
        message = await self._execute(event, intent)
        await self._gateway.reply(event, message)

    async def _execute(self, event: QQEvent, intent: CommandIntent) -> OutboundMessage:
        today = self._clock.now().astimezone(self._timezone).date()
        if intent.kind is CommandKind.TODAY:
            value = date.fromisoformat(intent.arguments[0]) if intent.arguments else today
            return render_listing(
                f"{value.isoformat()} 番剧", await self._catalog.list_day(value), self._timezone
            )
        if intent.kind is CommandKind.WEEK:
            return render_listing("本周番剧", await self._catalog.list_week(today), self._timezone)
        if intent.kind is CommandKind.SEASON:
            season = self._season(intent.arguments, today)
            return render_listing(
                f"{season.year} 年{season.name.value}季番剧",
                await self._catalog.list_season(season),
                self._timezone,
            )
        if intent.kind is CommandKind.SEARCH:
            return render_search(await self._catalog.search(" ".join(intent.arguments)))
        if intent.kind in {CommandKind.DETAIL, CommandKind.NEXT_AIRING}:
            detail = await self._resolve(" ".join(intent.arguments))
            if detail is None:
                return OutboundMessage("没有找到对应番剧。")
            if intent.kind is CommandKind.DETAIL:
                return render_detail(detail)
            occurrence = await self._catalog.get_next_airing(
                detail.subject_id, after=self._clock.now()
            )
            return render_next(detail, occurrence, self._timezone)
        if intent.kind in {CommandKind.SUBSCRIBE, CommandKind.UNSUBSCRIBE}:
            detail = await self._resolve(" ".join(intent.arguments))
            if detail is None:
                return OutboundMessage("没有找到对应番剧。")
            result = (
                await self._subscriptions.subscribe(event, detail.subject_id)
                if intent.kind is CommandKind.SUBSCRIBE
                else await self._subscriptions.unsubscribe(event, detail.subject_id)
            )
            if result.error:
                return OutboundMessage(result.error)
            return OutboundMessage(
                f"{detail.title}：{result.change.value if result.change else '未变更'}"
            )
        if intent.kind is CommandKind.MY_SUBSCRIPTIONS:
            subject_ids = await self._subscriptions.mine(event)
            details = [await self._catalog.get_detail(item) for item in subject_ids]
            titles = [item.title for item in details if item is not None and not item.nsfw]
            return OutboundMessage(
                "我的订阅：\n" + "\n".join(f"• {title}" for title in titles)
                if titles
                else "当前群暂无订阅。"
            )
        return OutboundMessage(HELP_TEXT)

    async def _resolve(self, value: str) -> AnimeDetail | None:
        if value.isdigit():
            return await self._catalog.get_detail(int(value))
        results = await self._catalog.search(value)
        return await self._catalog.get_detail(results[0].subject_id) if len(results) == 1 else None

    async def _reply(self, event: QQEvent, text: str) -> None:
        await self._gateway.reply(event, OutboundMessage(text))

    @staticmethod
    def _season(arguments: tuple[str, ...], today: date) -> Season:
        names = {item.value: item for item in SeasonName}
        if not arguments:
            return Season.from_date(today)
        if len(arguments) == 1:
            return Season(today.year, names[arguments[0]])
        return Season(int(arguments[0]), names[arguments[1]])
