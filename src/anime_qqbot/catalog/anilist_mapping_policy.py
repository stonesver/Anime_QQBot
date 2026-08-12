"""Persisted, operator-controlled guardrails for AniList link discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.catalog import AniListMappingPolicy


@dataclass(frozen=True)
class AniListMappingPolicyValues:
    """Effective values for one discovery pass.

    These defaults deliberately stay conservative: ``query_budget`` counts
    actual AniList *search* requests, rather than candidate shows.
    """

    query_budget: int = 12
    priority_window_days: int = 7
    retry_cooldown_hours: int = 24
    animeschedule_enabled: bool = False
    animeschedule_query_budget: int = 12
    animeschedule_priority_window_days: int = 7
    animeschedule_empty_cooldown_hours: int = 168
    animeschedule_error_cooldown_hours: int = 168


DEFAULT_ANILIST_MAPPING_POLICY = AniListMappingPolicyValues()


class AniListMappingPolicyRepository:
    """Read/write the singleton mapping policy without involving plugin config."""

    _KEY = "default"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def is_missing(self) -> bool:
        async with self._sessions() as session:
            return await session.get(AniListMappingPolicy, self._KEY) is None

    async def get(self) -> AniListMappingPolicyValues:
        async with self._sessions() as session:
            row = await session.get(AniListMappingPolicy, self._KEY)
        if row is None:
            return DEFAULT_ANILIST_MAPPING_POLICY
        return AniListMappingPolicyValues(
            query_budget=row.query_budget,
            priority_window_days=row.priority_window_days,
            retry_cooldown_hours=row.retry_cooldown_hours,
            animeschedule_enabled=row.animeschedule_enabled,
            animeschedule_query_budget=row.animeschedule_query_budget,
            animeschedule_priority_window_days=row.animeschedule_priority_window_days,
            animeschedule_empty_cooldown_hours=row.animeschedule_empty_cooldown_hours,
            animeschedule_error_cooldown_hours=row.animeschedule_error_cooldown_hours,
        )

    async def update(
        self,
        *,
        query_budget: int,
        priority_window_days: int,
        retry_cooldown_hours: int,
        animeschedule_enabled: bool = False,
        animeschedule_query_budget: int = 12,
        animeschedule_priority_window_days: int = 7,
        animeschedule_empty_cooldown_hours: int = 168,
        animeschedule_error_cooldown_hours: int = 168,
        now: datetime | None = None,
    ) -> AniListMappingPolicyValues:
        now = now or datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            row = await session.get(AniListMappingPolicy, self._KEY, with_for_update=True)
            if row is None:
                session.add(
                    AniListMappingPolicy(
                        key=self._KEY,
                        query_budget=query_budget,
                        priority_window_days=priority_window_days,
                        retry_cooldown_hours=retry_cooldown_hours,
                        animeschedule_enabled=animeschedule_enabled,
                        animeschedule_query_budget=animeschedule_query_budget,
                        animeschedule_priority_window_days=animeschedule_priority_window_days,
                        animeschedule_empty_cooldown_hours=animeschedule_empty_cooldown_hours,
                        animeschedule_error_cooldown_hours=animeschedule_error_cooldown_hours,
                        updated_at=now,
                    )
                )
            else:
                row.query_budget = query_budget
                row.priority_window_days = priority_window_days
                row.retry_cooldown_hours = retry_cooldown_hours
                row.animeschedule_enabled = animeschedule_enabled
                row.animeschedule_query_budget = animeschedule_query_budget
                row.animeschedule_priority_window_days = animeschedule_priority_window_days
                row.animeschedule_empty_cooldown_hours = animeschedule_empty_cooldown_hours
                row.animeschedule_error_cooldown_hours = animeschedule_error_cooldown_hours
                row.updated_at = now
        return AniListMappingPolicyValues(
            query_budget=query_budget,
            priority_window_days=priority_window_days,
            retry_cooldown_hours=retry_cooldown_hours,
            animeschedule_enabled=animeschedule_enabled,
            animeschedule_query_budget=animeschedule_query_budget,
            animeschedule_priority_window_days=animeschedule_priority_window_days,
            animeschedule_empty_cooldown_hours=animeschedule_empty_cooldown_hours,
            animeschedule_error_cooldown_hours=animeschedule_error_cooldown_hours,
        )


__all__ = [
    "DEFAULT_ANILIST_MAPPING_POLICY",
    "AniListMappingPolicyRepository",
    "AniListMappingPolicyValues",
]
