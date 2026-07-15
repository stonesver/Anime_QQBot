from anime_qqbot.commands.agent import AgentRuntime
from anime_qqbot.commands.models import CommandIntent, CommandKind
from anime_qqbot.commands.parser import CommandParser
from anime_qqbot.qq.contracts import QQEvent, QQEventType


class CommandRouter:
    def __init__(self, parser: CommandParser, agent: AgentRuntime) -> None:
        self._parser = parser
        self._agent = agent

    async def route(self, event: QQEvent) -> CommandIntent | None:
        if event.event_type is QQEventType.BUTTON_INTERACTION:
            return self._parser.parse(event.button_data or "")
        if event.event_type not in {QQEventType.GROUP_AT_MESSAGE, QQEventType.C2C_MESSAGE}:
            return None
        intent = self._parser.parse(event.content)
        if intent.kind is CommandKind.HELP and intent.error and self._agent.enabled:
            return await self._agent.interpret(event) or intent
        return intent
