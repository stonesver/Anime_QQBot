from dataclasses import dataclass

from anime_qqbot.qq.contracts import QQEvent
from anime_qqbot.subscriptions.repository import SubscriptionChange, SubscriptionRepository


@dataclass(frozen=True)
class SubscriptionResult:
    change: SubscriptionChange | None
    error: str | None = None


class SubscriptionManager:
    def __init__(self, repository: SubscriptionRepository) -> None:
        self._repository = repository

    async def subscribe(self, event: QQEvent, subject_id: int) -> SubscriptionResult:
        context = self._group_context(event)
        if context is None:
            return SubscriptionResult(None, "请在希望接收提醒的目标群中订阅")
        return SubscriptionResult(await self._repository.subscribe(*context, subject_id))

    async def unsubscribe(self, event: QQEvent, subject_id: int) -> SubscriptionResult:
        context = self._group_context(event)
        if context is None:
            return SubscriptionResult(None, "请在目标群中取消订阅")
        return SubscriptionResult(await self._repository.unsubscribe(*context, subject_id))

    async def mine(self, event: QQEvent) -> list[int]:
        context = self._group_context(event)
        if context is None:
            return []
        return await self._repository.list_for_member(*context)

    @staticmethod
    def _group_context(event: QQEvent) -> tuple[str, str] | None:
        if not event.group_openid or not event.member_openid:
            return None
        return event.group_openid, event.member_openid
