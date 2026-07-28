"""Small interface for durable, user-triggered catalogue enrichment."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.operations.models import OperatorJobView
from anime_qqbot.operations.repository import OperatorJobRepository


class BackgroundEnrichmentQueue:
    """Hide operator-job details from query and subscription callers."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self._jobs = OperatorJobRepository(sessions)

    async def request_search(
        self,
        query: str,
        *,
        now: datetime,
    ) -> OperatorJobView:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("search enrichment requires a query")
        normalized = unicodedata.normalize("NFKC", clean_query).casefold()
        digest = hashlib.sha256(normalized.encode()).hexdigest()[:24]
        return await self._jobs.enqueue(
            "sync_catalog",
            {"trigger": "search_miss", "query": clean_query},
            idempotency_key=f"chat-search:{_ten_minute_bucket(now)}:{digest}",
            now=now,
        )

    async def request_subscription(
        self,
        anime_id: UUID,
        *,
        now: datetime,
    ) -> OperatorJobView:
        return await self._jobs.enqueue(
            "sync_catalog",
            {"trigger": "subscription", "anime_id": str(anime_id)},
            idempotency_key=(f"chat-subscription:{_ten_minute_bucket(now)}:{anime_id}"),
            now=now,
        )


def _ten_minute_bucket(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    utc_now = now.astimezone(UTC)
    return f"{utc_now:%Y%m%d%H}{utc_now.minute // 10}"


__all__ = ["BackgroundEnrichmentQueue"]
