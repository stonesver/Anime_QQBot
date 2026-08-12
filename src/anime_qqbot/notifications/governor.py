"""In-process scheduling policy shared by replies and proactive messages."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from anime_qqbot.clock import Clock, SystemClock


class DeliveryClass(StrEnum):
    INTERACTIVE = "interactive"
    AIRING = "airing"
    RELEASE = "release"
    CONTENT = "content"
    ADMIN = "admin"

    @property
    def proactive(self) -> bool:
        return self in {DeliveryClass.AIRING, DeliveryClass.RELEASE, DeliveryClass.CONTENT}


@dataclass(frozen=True)
class SendRequest:
    delivery_class: DeliveryClass
    group_id: str
    user_id: str | None = None


@dataclass(frozen=True)
class SendPermit:
    allowed: bool
    retry_after_seconds: float = 0
    reason: str | None = None


@dataclass(frozen=True)
class GovernorLimits:
    global_interval_seconds: float = 2.5
    global_burst: int = 2
    group_interval_seconds: float = 5
    user_interval_seconds: float = 5
    user_limit_per_minute: int = 10
    proactive_group_interval_seconds: float = 60
    proactive_group_limit_per_10_minutes: int = 3


class SendGovernor:
    """Returns immediate permits; callers decide whether to retry later.

    It deliberately never sleeps inside a request handler. The outbox can
    simply leave work pending, while an interactive handler can return a
    concise cooldown hint.
    """

    def __init__(
        self,
        *,
        limits: GovernorLimits | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._limits = limits or GovernorLimits()
        self._clock = clock or SystemClock()
        self._global: deque[datetime] = deque()
        self._group_last: dict[str, datetime] = {}
        self._user_last: dict[tuple[str, str], datetime] = {}
        self._user_window: defaultdict[tuple[str, str], deque[datetime]] = defaultdict(deque)
        self._proactive_last: dict[str, datetime] = {}
        self._proactive_window: defaultdict[str, deque[datetime]] = defaultdict(deque)

    def acquire(self, request: SendRequest) -> SendPermit:
        now = self._clock.now()
        waits = self._waits(request, now)
        if waits:
            reason, wait = max(waits, key=lambda item: item[1])
            return SendPermit(False, max(0.01, wait), reason)
        self._record(request, now)
        return SendPermit(True)

    def peek(self, request: SendRequest) -> SendPermit:
        now = self._clock.now()
        waits = self._waits(request, now)
        if not waits:
            return SendPermit(True)
        reason, wait = max(waits, key=lambda item: item[1])
        return SendPermit(False, max(0.01, wait), reason)

    def _waits(self, request: SendRequest, now: datetime) -> list[tuple[str, float]]:
        waits: list[tuple[str, float]] = []
        self._prune(self._global, now - timedelta(seconds=self._limits.global_interval_seconds))
        if len(self._global) >= self._limits.global_burst:
            waits.append(
                (
                    "global",
                    self._seconds_until(
                        self._global[0],
                        now,
                        self._limits.global_interval_seconds,
                    ),
                )
            )
        group_last = self._group_last.get(request.group_id)
        if group_last is not None:
            waits.append(
                (
                    "group",
                    self._seconds_until(group_last, now, self._limits.group_interval_seconds),
                )
            )
        if request.user_id is not None:
            key = (request.group_id, request.user_id)
            last = self._user_last.get(key)
            if last is not None:
                waits.append(
                    (
                        "user",
                        self._seconds_until(last, now, self._limits.user_interval_seconds),
                    )
                )
            window = self._user_window[key]
            self._prune(window, now - timedelta(minutes=1))
            if len(window) >= self._limits.user_limit_per_minute:
                waits.append(
                    ("user_window", (window[0] + timedelta(minutes=1) - now).total_seconds())
                )
        if request.delivery_class.proactive:
            last = self._proactive_last.get(request.group_id)
            if last is not None:
                waits.append(
                    (
                        "proactive_group",
                        self._seconds_until(
                            last,
                            now,
                            self._limits.proactive_group_interval_seconds,
                        ),
                    )
                )
            window = self._proactive_window[request.group_id]
            self._prune(window, now - timedelta(minutes=10))
            if len(window) >= self._limits.proactive_group_limit_per_10_minutes:
                waits.append(
                    (
                        "proactive_window",
                        (window[0] + timedelta(minutes=10) - now).total_seconds(),
                    )
                )
        return [(reason, wait) for reason, wait in waits if wait > 0]

    def _record(self, request: SendRequest, now: datetime) -> None:
        self._global.append(now)
        self._group_last[request.group_id] = now
        if request.user_id is not None:
            key = (request.group_id, request.user_id)
            self._user_last[key] = now
            self._user_window[key].append(now)
        if request.delivery_class.proactive:
            self._proactive_last[request.group_id] = now
            self._proactive_window[request.group_id].append(now)

    @staticmethod
    def _prune(values: deque[datetime], cutoff: datetime) -> None:
        while values and values[0] <= cutoff:
            values.popleft()

    @staticmethod
    def _seconds_until(last: datetime, now: datetime, interval: float) -> float:
        return (last + timedelta(seconds=interval) - now).total_seconds()


__all__ = [
    "DeliveryClass",
    "GovernorLimits",
    "SendGovernor",
    "SendPermit",
    "SendRequest",
]
