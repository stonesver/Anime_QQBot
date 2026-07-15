from datetime import UTC, date, datetime

from anime_qqbot.catalog.models import AnimeDetail
from anime_qqbot.clock import FrozenClock
from anime_qqbot.commands.agent import DisabledAgentRuntime
from anime_qqbot.commands.handlers import CommandHandler
from anime_qqbot.commands.parser import CommandParser
from anime_qqbot.commands.router import CommandRouter
from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.qq.fake import FakeQQGateway
from anime_qqbot.subscriptions.module import SubscriptionResult
from anime_qqbot.subscriptions.repository import SubscriptionChange


class CatalogStub:
    async def get_detail(self, subject_id: int) -> AnimeDetail:
        return AnimeDetail(subject_id, "订阅番", "Subscribe", date(2026, 7, 1))


class SubscriptionStub:
    async def subscribe(self, event: QQEvent, subject_id: int) -> SubscriptionResult:
        assert event.group_openid == "group" and subject_id == 1001
        return SubscriptionResult(SubscriptionChange.ADDED)


async def test_group_subscription_command_uses_group_scoped_context() -> None:
    gateway = FakeQQGateway()
    handler = CommandHandler(
        CommandRouter(CommandParser(), DisabledAgentRuntime()),
        CatalogStub(),  # type: ignore[arg-type]
        SubscriptionStub(),  # type: ignore[arg-type]
        gateway,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
    )
    event = QQEvent(
        "event",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        content="订阅 1001",
        group_openid="group",
        member_openid="member",
    )

    await handler.handle(event)

    assert "added" in gateway.replies[0][1].text
