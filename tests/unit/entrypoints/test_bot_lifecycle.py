from datetime import UTC, datetime

from anime_qqbot.entrypoints.bot import BotRuntime
from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.qq.fake import FakeQQGateway


class RecordingHandler:
    def __init__(self) -> None:
        self.events: list[QQEvent] = []

    async def handle(self, event: QQEvent) -> None:
        self.events.append(event)


async def test_bot_consumes_gateway_events_and_becomes_not_ready_on_exit() -> None:
    event = QQEvent("event", QQEventType.C2C_MESSAGE, datetime.now(UTC), user_openid="user")
    handler = RecordingHandler()
    runtime = BotRuntime(FakeQQGateway([event]), handler)

    await runtime.run()

    assert handler.events == [event]
    assert runtime.ready is False
