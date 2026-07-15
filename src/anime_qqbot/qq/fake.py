from collections.abc import AsyncIterator

from anime_qqbot.qq.contracts import (
    DeliveryOutcome,
    DeliveryResult,
    OutboundMessage,
    QQEvent,
)


class FakeQQGateway:
    def __init__(self, events: list[QQEvent] | None = None) -> None:
        self.pending_events = list(events or [])
        self.replies: list[tuple[QQEvent, OutboundMessage]] = []
        self.group_messages: list[tuple[str, OutboundMessage]] = []
        self.next_result = DeliveryResult(DeliveryOutcome.SENT, "fake-message")

    async def events(self) -> AsyncIterator[QQEvent]:
        for event in self.pending_events:
            yield event

    async def reply(self, event: QQEvent, message: OutboundMessage) -> DeliveryResult:
        self.replies.append((event, message))
        return self.next_result

    async def send_group(self, group_openid: str, message: OutboundMessage) -> DeliveryResult:
        self.group_messages.append((group_openid, message))
        return self.next_result

    def fail_next(
        self,
        outcome: DeliveryOutcome,
        *,
        retry_after_seconds: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.next_result = DeliveryResult(
            outcome, retry_after_seconds=retry_after_seconds, error_code=error_code
        )
