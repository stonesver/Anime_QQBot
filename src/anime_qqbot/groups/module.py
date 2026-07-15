from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.qq.contracts import QQEvent


class GroupManager:
    def __init__(self, repository: GroupRepository) -> None:
        self._repository = repository

    async def accept_event(self, event: QQEvent) -> bool:
        if not await self._repository.claim_event(event):
            return False
        await self._repository.observe(event)
        return True
