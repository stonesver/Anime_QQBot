"""Airing notification planner (Task 18)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.subscriptions.repository_v2 import FollowRepository


@dataclass(frozen=True)
class AiringEvent:
    anime_id: UUID
    episode_label: str
    air_at: object  # datetime with tzinfo
    display_title: str


class AiringPlanner:
    def __init__(
        self,
        follow_repo: FollowRepository,
        outbox: OutboxRepository,
    ) -> None:
        self._follow = follow_repo
        self._outbox = outbox

    async def plan_airing(self, event: AiringEvent) -> int:
        from datetime import datetime as _dt

        if not isinstance(event.air_at, _dt):
            return 0

        subs = await self._follow.active_subscribers_for_anime(event.anime_id)
        if not subs:
            return 0

        groups: dict[UUID, list[str]] = {}
        for sub in subs:
            groups.setdefault(sub.chat_group_id, []).append(sub.external_user_id)

        created = 0
        for chat_group_id, user_ids in groups.items():
            business_key = f"airing/{event.anime_id}/{event.episode_label}"
            await self._outbox.enqueue(
                chat_group_id=chat_group_id,
                job_type="airing",
                business_key=business_key,
                payload={
                    "anime_id": str(event.anime_id),
                    "display_title": event.display_title,
                    "episode_label": event.episode_label,
                    "air_at": event.air_at.isoformat(),
                    "user_ids": user_ids,
                },
                available_at=event.air_at,
                expires_at=event.air_at + timedelta(hours=2),
            )
            created += 1
        return created


__all__ = ["AiringEvent", "AiringPlanner"]
