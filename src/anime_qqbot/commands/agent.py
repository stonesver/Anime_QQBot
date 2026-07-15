from typing import Protocol

from anime_qqbot.commands.models import CommandIntent
from anime_qqbot.qq.contracts import QQEvent


class AgentRuntime(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def interpret(self, event: QQEvent) -> CommandIntent | None: ...


class DisabledAgentRuntime:
    @property
    def enabled(self) -> bool:
        return False

    async def interpret(self, event: QQEvent) -> CommandIntent | None:
        del event
        return None
