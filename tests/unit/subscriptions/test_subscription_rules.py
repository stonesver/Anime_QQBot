from datetime import UTC, datetime

from anime_qqbot.qq.contracts import QQEvent, QQEventType
from anime_qqbot.subscriptions.module import SubscriptionManager


class NeverCalledRepository:
    async def subscribe(self, *_: object) -> None:
        raise AssertionError("repository must not be called")


async def test_private_subscription_is_rejected_with_group_instruction() -> None:
    event = QQEvent(
        "event",
        QQEventType.C2C_MESSAGE,
        datetime.now(UTC),
        user_openid="user",
    )
    manager = SubscriptionManager(NeverCalledRepository())  # type: ignore[arg-type]

    result = await manager.subscribe(event, 1001)

    assert result.change is None
    assert result.error == "请在希望接收提醒的目标群中订阅"
