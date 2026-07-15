from datetime import UTC, datetime

from anime_qqbot.qq.contracts import OutboundMessage, QQEvent, QQEventType
from anime_qqbot.qq.fake import FakeQQGateway


async def test_fake_gateway_records_event_reply_and_active_message() -> None:
    event = QQEvent(
        "event-1",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        group_openid="group-1",
        member_openid="member-1",
    )
    gateway = FakeQQGateway([event])

    received = [item async for item in gateway.events()]
    await gateway.reply(received[0], OutboundMessage("reply"))
    await gateway.send_group("group-1", OutboundMessage("push"))

    assert gateway.replies[0][1].text == "reply"
    assert gateway.group_messages[0][1].text == "push"
