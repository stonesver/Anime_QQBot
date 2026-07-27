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
        return AnimeDetail(
            subject_id,
            f"订阅番 {subject_id}",
            "Subscribe",
            date(2026, 7, 1),
            image_url=f"https://example.test/subscription-{subject_id}.jpg",
        )


class SubscriptionStub:
    async def subscribe(self, event: QQEvent, subject_id: int) -> SubscriptionResult:
        assert event.group_openid == "group" and subject_id == 1001
        return SubscriptionResult(SubscriptionChange.ADDED)

    async def mine(self, event: QQEvent) -> list[int]:
        assert event.group_openid == "group"
        return list(range(1, 7))


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

    message = gateway.replies[0][1]
    assert "added" in message.text
    assert message.markdown is not None
    assert "# ✅ 订阅成功" in message.markdown
    assert "订阅番" in message.markdown
    assert "已添加" in message.markdown


async def test_my_subscriptions_uses_the_same_adaptive_card_presentation() -> None:
    gateway = FakeQQGateway()
    handler = CommandHandler(
        CommandRouter(CommandParser(), DisabledAgentRuntime()),
        CatalogStub(),  # type: ignore[arg-type]
        SubscriptionStub(),  # type: ignore[arg-type]
        gateway,
        FrozenClock(datetime(2026, 7, 15, tzinfo=UTC)),
    )
    event = QQEvent(
        "event-mine",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        content="我的订阅",
        group_openid="group",
        member_openid="member",
    )

    await handler.handle(event)

    message = gateway.replies[0][1]
    assert message.markdown is not None
    assert message.markdown.count("https://example.test/subscription-") == 5
    assert message.buttons[0].data == "我的订阅 --page=2"
