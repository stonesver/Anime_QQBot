from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class NapCatStatus(StrEnum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    QQ_OFFLINE = "qq_offline"
    UNREACHABLE = "unreachable"


class ProbeOutcome(StrEnum):
    ONLINE = "online"
    QQ_OFFLINE = "qq_offline"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class NapCatProbeResult:
    outcome: ProbeOutcome

    @classmethod
    def online(cls) -> NapCatProbeResult:
        return cls(ProbeOutcome.ONLINE)

    @classmethod
    def qq_offline(cls) -> NapCatProbeResult:
        return cls(ProbeOutcome.QQ_OFFLINE)

    @classmethod
    def failure(cls) -> NapCatProbeResult:
        return cls(ProbeOutcome.FAILURE)


@dataclass(frozen=True, slots=True)
class NapCatStatusSnapshot:
    status: NapCatStatus
    consecutive_failures: int
    status_changed_at: datetime
    observed_at: datetime
    offline_since: datetime | None


@dataclass(frozen=True, slots=True)
class NapCatStatusEvent:
    previous_status: NapCatStatus | None
    status: NapCatStatus
    summary: str
    occurred_at: datetime


class NapCatStatusTracker:
    def __init__(self, snapshot: NapCatStatusSnapshot | None = None) -> None:
        self._snapshot = snapshot

    def observe(
        self,
        result: NapCatProbeResult,
        *,
        observed_at: datetime,
    ) -> NapCatStatusSnapshot:
        current = self._snapshot
        if result.outcome is ProbeOutcome.ONLINE:
            status = NapCatStatus.ONLINE
            offline_since = None
        elif result.outcome is ProbeOutcome.QQ_OFFLINE:
            status = NapCatStatus.QQ_OFFLINE
            offline_since = (
                current.offline_since
                if current is not None and current.offline_since is not None
                else observed_at
            )
        else:
            failures = (current.consecutive_failures if current is not None else 0) + 1
            status = (
                NapCatStatus.UNREACHABLE
                if failures >= 3
                else current.status
                if current is not None
                else NapCatStatus.UNKNOWN
            )
            offline_since = current.offline_since if current is not None else None

        changed_at = (
            current.status_changed_at
            if current is not None and current.status is status
            else observed_at
        )
        snapshot = NapCatStatusSnapshot(
            status=status,
            consecutive_failures=(
                (current.consecutive_failures if current is not None else 0) + 1
                if result.outcome is ProbeOutcome.FAILURE
                else 0
            ),
            status_changed_at=changed_at,
            observed_at=observed_at,
            offline_since=offline_since,
        )
        self._snapshot = snapshot
        return snapshot


class NapCatOneBotClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/get_status"
        self._token = token
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=3.0),
        )

    async def probe(self) -> NapCatProbeResult:
        try:
            response = await self._http.post(
                self._url,
                headers={"Authorization": f"Bearer {self._token}"},
                json={},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, TypeError, ValueError):
            return NapCatProbeResult.failure()
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "ok"
            or payload.get("retcode") != 0
        ):
            return NapCatProbeResult.failure()
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("online"), bool):
            return NapCatProbeResult.failure()
        if data["online"] is True and data.get("good") is not False:
            return NapCatProbeResult.online()
        return NapCatProbeResult.qq_offline()

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()


class NapCatGroupContentClient:
    """Narrow OneBot client for @all quota and weekly essence actions."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0))

    async def at_all_remaining(self, group_id: str) -> int | None:
        data = await self._action("get_group_at_all_remain", {"group_id": group_id})
        if not isinstance(data, dict) or data.get("can_at_all") is not True:
            return None
        remaining = data.get("remain_at_all_count_for_group")
        return remaining if isinstance(remaining, int) and remaining >= 0 else None

    async def set_essence(self, message_id: str) -> bool:
        return await self._succeeded("set_essence_msg", {"message_id": message_id})

    async def delete_essence(self, message_id: str) -> bool:
        return await self._succeeded("delete_essence_msg", {"message_id": message_id})

    async def _succeeded(self, action: str, payload: dict[str, object]) -> bool:
        marker = object()
        return await self._action(action, payload, failure=marker) is not marker

    async def _action(
        self,
        action: str,
        payload: dict[str, object],
        *,
        failure: object | None = None,
    ) -> object | None:
        try:
            response = await self._http.post(
                f"{self._base_url}/{action}",
                headers={"Authorization": f"Bearer {self._token}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, TypeError, ValueError):
            return failure
        if not isinstance(body, dict) or body.get("status") != "ok" or body.get("retcode") != 0:
            return failure
        return body.get("data")

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()


class StatusProbe(Protocol):
    async def probe(self) -> NapCatProbeResult: ...

    async def close(self) -> None: ...


class StatusStore(Protocol):
    async def get(self, component_name: str) -> NapCatStatusSnapshot | None: ...

    async def record(
        self,
        component_name: str,
        snapshot: NapCatStatusSnapshot,
    ) -> bool: ...


class NapCatStatusMonitor:
    def __init__(
        self,
        *,
        client: StatusProbe,
        repository: StatusStore,
        interval_seconds: float = 60,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._client = client
        self._repository = repository
        self._interval_seconds = interval_seconds
        self._stop = asyncio.Event()
        self._persistence_warning_active = False

    async def run(self) -> None:
        try:
            tracker = NapCatStatusTracker(await self._load_snapshot())
            while not self._stop.is_set():
                result = await self._client.probe()
                observed_at = datetime.now(UTC)
                snapshot = tracker.observe(result, observed_at=observed_at)
                try:
                    changed = await self._repository.record("napcat", snapshot)
                except Exception as exc:
                    if not self._persistence_warning_active:
                        logger.warning(
                            "napcat_status.persistence_failed",
                            extra={"error_type": type(exc).__name__},
                        )
                        self._persistence_warning_active = True
                else:
                    self._persistence_warning_active = False
                    if changed:
                        logger.info(
                            "napcat_status.changed",
                            extra={"status": snapshot.status.value},
                        )
                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=self._interval_seconds,
                    )
                except TimeoutError:
                    continue
        finally:
            await self._client.close()

    async def stop(self) -> None:
        self._stop.set()

    async def _load_snapshot(self) -> NapCatStatusSnapshot | None:
        try:
            return await self._repository.get("napcat")
        except Exception as exc:
            logger.warning(
                "napcat_status.initial_state_unavailable",
                extra={"error_type": type(exc).__name__},
            )
            return None


__all__ = [
    "NapCatGroupContentClient",
    "NapCatOneBotClient",
    "NapCatProbeResult",
    "NapCatStatus",
    "NapCatStatusEvent",
    "NapCatStatusMonitor",
    "NapCatStatusSnapshot",
    "NapCatStatusTracker",
]
