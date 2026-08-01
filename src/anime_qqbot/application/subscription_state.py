"""Pure rules for deciding what a new anime subscription should follow."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SubscriptionStateKind(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"


@dataclass(frozen=True)
class SubscriptionOccurrence:
    episode_label: str
    air_at: datetime


@dataclass(frozen=True)
class SubscriptionState:
    kind: SubscriptionStateKind
    latest_episode: int | None
    next_occurrence: SubscriptionOccurrence | None


def classify_subscription(
    *,
    next_occurrence: SubscriptionOccurrence | None,
    latest_episode: int | None,
    total_episodes: int | None,
    source_statuses: Iterable[str],
) -> SubscriptionState:
    """Classify a subscription using only trustworthy catalog facts.

    Missing schedules are deliberately not treated as completion. A source
    status of ``FINISHED`` or reaching a known positive episode total is the
    only evidence that suppresses both airing and resource subscriptions.
    """

    normalized_statuses = {
        status.strip().casefold() for status in source_statuses if status.strip()
    }
    status_finished = bool(
        normalized_statuses.intersection({"finished", "complete", "completed", "完结"})
    )
    reached_total = (
        total_episodes is not None
        and total_episodes > 0
        and latest_episode is not None
        and latest_episode >= total_episodes
    )
    if status_finished or reached_total:
        return SubscriptionState(
            kind=SubscriptionStateKind.COMPLETED,
            latest_episode=latest_episode,
            next_occurrence=None,
        )
    if next_occurrence is not None:
        return SubscriptionState(
            kind=SubscriptionStateKind.ACTIVE,
            latest_episode=latest_episode,
            next_occurrence=next_occurrence,
        )
    return SubscriptionState(
        kind=SubscriptionStateKind.WAITING,
        latest_episode=latest_episode,
        next_occurrence=None,
    )


__all__ = [
    "SubscriptionOccurrence",
    "SubscriptionState",
    "SubscriptionStateKind",
    "classify_subscription",
]
