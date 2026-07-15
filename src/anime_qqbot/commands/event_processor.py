from typing import Protocol

from anime_qqbot.groups.module import GroupManager
from anime_qqbot.qq.contracts import QQEvent


class EventHandler(Protocol):
    async def handle(self, event: QQEvent) -> None: ...


class EventProcessor:
    def __init__(self, groups: GroupManager, handler: EventHandler) -> None:
        self._groups = groups
        self._handler = handler

    async def process(self, event: QQEvent) -> bool:
        if not await self._groups.accept_event(event):
            return False
        await self._handler.handle(event)
        return True
