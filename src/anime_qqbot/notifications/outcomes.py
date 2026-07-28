from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeliveryOutcomeKind(StrEnum):
    SENT = "sent"
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"
    ACCOUNT_OFFLINE = "account_offline"


@dataclass(frozen=True)
class DeliveryOutcome:
    kind: DeliveryOutcomeKind
    summary: str
    retry_after_seconds: float | None = None

    @property
    def retryable(self) -> bool:
        return self.kind in {
            DeliveryOutcomeKind.TEMPORARY,
            DeliveryOutcomeKind.RATE_LIMITED,
        }

    @property
    def opens_global_circuit(self) -> bool:
        return self.kind == DeliveryOutcomeKind.ACCOUNT_OFFLINE
