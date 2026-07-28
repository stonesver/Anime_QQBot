from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class InteractionScope:
    platform: str
    external_group_id: str
    external_user_id: str


@dataclass(frozen=True)
class CandidateItem:
    anime_id: UUID
    title: str
    subtitle: str | None = None


@dataclass(frozen=True)
class SessionView:
    id: UUID
    scope: InteractionScope
    candidates: tuple[CandidateItem, ...]
    result_message_id: str | None
    created_at: datetime
    expires_at: datetime

    def candidate(self, number: int) -> CandidateItem | None:
        if number < 1 or number > len(self.candidates):
            return None
        return self.candidates[number - 1]
