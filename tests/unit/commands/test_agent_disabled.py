from datetime import UTC, datetime

from anime_qqbot.commands.agent import DisabledAgentRuntime
from anime_qqbot.commands.models import CommandKind
from anime_qqbot.commands.parser import CommandParser
from anime_qqbot.commands.router import CommandRouter
from anime_qqbot.qq.contracts import QQEvent, QQEventType


async def test_disabled_agent_never_interprets_unknown_text() -> None:
    event = QQEvent(
        "event",
        QQEventType.C2C_MESSAGE,
        datetime.now(UTC),
        content="自然语言问题",
        user_openid="user",
    )
    runtime = DisabledAgentRuntime()

    intent = await CommandRouter(CommandParser(), runtime).route(event)

    assert runtime.enabled is False
    assert intent is not None and intent.kind is CommandKind.HELP
