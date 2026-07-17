import logging
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from anime_qqbot.catalog.models import AnimeDetail, Season, SeasonName
from anime_qqbot.catalog.module import AnimeCatalog
from anime_qqbot.clock import Clock
from anime_qqbot.commands.models import CommandIntent, CommandKind
from anime_qqbot.commands.router import CommandRouter
from anime_qqbot.qq.contracts import (
    DeliveryOutcome,
    DeliveryResult,
    OutboundMessage,
    QQEvent,
    QQEventType,
)
from anime_qqbot.qq.gateway import QQGateway
from anime_qqbot.qq.rendering import (
    render_detail,
    render_help,
    render_listing,
    render_next,
    render_search,
    render_subjects,
    render_subscription_status,
)
from anime_qqbot.subscriptions.module import SubscriptionManager

logger = logging.getLogger(__name__)


class ScheduleAdmin(Protocol):
    async def handle(
        self, event: QQEvent, intent: CommandIntent, now: datetime
    ) -> OutboundMessage: ...


class CommandHandler:
    def __init__(
        self,
        router: CommandRouter,
        catalog: AnimeCatalog,
        subscriptions: SubscriptionManager,
        gateway: QQGateway,
        clock: Clock,
        timezone: str = "Asia/Shanghai",
        schedule_admin: ScheduleAdmin | None = None,
        image_proxy_base_url: str | None = None,
    ) -> None:
        self._router = router
        self._catalog = catalog
        self._subscriptions = subscriptions
        self._gateway = gateway
        self._clock = clock
        self._timezone = ZoneInfo(timezone)
        self._schedule_admin = schedule_admin
        self._image_proxy_base_url = image_proxy_base_url

    async def handle(self, event: QQEvent) -> None:
        if event.event_type is QQEventType.BUTTON_INTERACTION:
            acknowledgement = await self._gateway.acknowledge_interaction(event)
            self._log_failed_delivery("acknowledge_interaction", acknowledgement)
        intent = await self._router.route(event)
        if intent is None:
            return
        if not intent.valid:
            await self._reply(event, intent.error or "参数错误")
            return
        message = await self._execute(event, intent)
        result = await self._gateway.reply(event, message)
        self._log_failed_delivery("reply", result)

    async def _execute(self, event: QQEvent, intent: CommandIntent) -> OutboundMessage:
        admin_kinds = {
            CommandKind.ENABLE_DAILY,
            CommandKind.DISABLE_DAILY,
            CommandKind.ENABLE_WEEKLY,
            CommandKind.DISABLE_WEEKLY,
            CommandKind.SET_TIMEZONE,
            CommandKind.PUSH_STATUS,
            CommandKind.PUSH_TODAY_NOW,
            CommandKind.REDELIVER,
        }
        if intent.kind in admin_kinds:
            if self._schedule_admin is None:
                return OutboundMessage("推送管理模块尚未启用。")
            return await self._schedule_admin.handle(event, intent, self._clock.now())
        today = self._clock.now().astimezone(self._timezone).date()
        if intent.kind is CommandKind.TODAY:
            value = date.fromisoformat(intent.arguments[0]) if intent.arguments else today
            return render_listing(
                f"{value.isoformat()} 番剧",
                await self._catalog.list_day(value),
                self._timezone,
                command=f"今日番剧 {value.isoformat()}",
                page=intent.page,
                force_compact=intent.force_compact,
                image_proxy_base_url=self._image_proxy_base_url,
            )
        if intent.kind is CommandKind.WEEK:
            return render_listing(
                "本周番剧",
                await self._catalog.list_week(today),
                self._timezone,
                command="本周番剧",
                page=intent.page,
                force_compact=intent.force_compact,
                image_proxy_base_url=self._image_proxy_base_url,
            )
        if intent.kind is CommandKind.SEASON:
            season = self._season(intent.arguments, today)
            return render_listing(
                f"{season.year} 年{season.name.value}季番剧",
                await self._catalog.list_season(season),
                self._timezone,
                command=f"季度番剧 {season.year} {season.name.value}",
                page=intent.page,
                force_compact=intent.force_compact,
                image_proxy_base_url=self._image_proxy_base_url,
            )
        if intent.kind is CommandKind.SEARCH:
            query = " ".join(intent.arguments)
            return render_search(
                await self._catalog.search(query),
                command=f"搜索 {query}",
                page=intent.page,
                force_compact=intent.force_compact,
                image_proxy_base_url=self._image_proxy_base_url,
            )
        if intent.kind in {CommandKind.DETAIL, CommandKind.NEXT_AIRING}:
            detail = await self._resolve(" ".join(intent.arguments))
            if detail is None:
                return OutboundMessage("没有找到对应番剧。")
            if intent.kind is CommandKind.DETAIL:
                return render_detail(detail, image_proxy_base_url=self._image_proxy_base_url)
            occurrence = await self._catalog.get_next_airing(
                detail.subject_id, after=self._clock.now()
            )
            return render_next(
                detail,
                occurrence,
                self._timezone,
                image_proxy_base_url=self._image_proxy_base_url,
            )
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
            return render_subscription_status(
                detail.title,
                result.change.value if result.change else "未变更",
            )
        if intent.kind is CommandKind.MY_SUBSCRIPTIONS:
            subject_ids = await self._subscriptions.mine(event)
            details = [await self._catalog.get_detail(item) for item in subject_ids]
            subjects = [item.as_summary() for item in details if item is not None and not item.nsfw]
            if not subjects:
                return OutboundMessage("当前群暂无订阅。")
            return render_subjects(
                "我的订阅",
                subjects,
                command="我的订阅",
                page=intent.page,
                force_compact=intent.force_compact,
                image_proxy_base_url=self._image_proxy_base_url,
            )
        return render_help()

    async def _resolve(self, value: str) -> AnimeDetail | None:
        if value.isdigit():
            return await self._catalog.get_detail(int(value))
        results = await self._catalog.search(value)
        return await self._catalog.get_detail(results[0].subject_id) if len(results) == 1 else None

    async def _reply(self, event: QQEvent, text: str) -> None:
        result = await self._gateway.reply(event, OutboundMessage(text))
        self._log_failed_delivery("reply", result)

    @staticmethod
    def _log_failed_delivery(operation: str, result: DeliveryResult) -> None:
        if result.outcome is DeliveryOutcome.SENT:
            return
        logger.warning(
            {
                "event": "qq_delivery_failed",
                "operation": operation,
                "outcome": result.outcome,
                "error_code": result.error_code,
            }
        )

    @staticmethod
    def _season(arguments: tuple[str, ...], today: date) -> Season:
        names = {item.value: item for item in SeasonName}
        if not arguments:
            return Season.from_date(today)
        if len(arguments) == 1:
            return Season(today.year, names[arguments[0]])
        return Season(int(arguments[0]), names[arguments[1]])
