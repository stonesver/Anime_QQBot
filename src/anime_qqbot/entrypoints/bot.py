import asyncio

from anime_qqbot.commands.event_processor import EventHandler
from anime_qqbot.qq.gateway import QQGateway


class BotRuntime:
    def __init__(self, gateway: QQGateway, handler: EventHandler) -> None:
        self._gateway = gateway
        self._handler = handler
        self._stopping = asyncio.Event()
        self.ready = False

    async def run(self) -> None:
        self.ready = True
        try:
            async for event in self._gateway.events():
                if self._stopping.is_set():
                    break
                await self._handler.handle(event)
        finally:
            self.ready = False

    def stop(self) -> None:
        self._stopping.set()
