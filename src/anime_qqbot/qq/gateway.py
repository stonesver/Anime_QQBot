from collections.abc import AsyncIterator
from typing import Protocol

from anime_qqbot.qq.contracts import DeliveryResult, OutboundMessage, QQEvent


class QQGateway(Protocol):
    def events(self) -> AsyncIterator[QQEvent]: ...

    async def reply(self, event: QQEvent, message: OutboundMessage) -> DeliveryResult: ...

    async def send_group(self, group_openid: str, message: OutboundMessage) -> DeliveryResult: ...
