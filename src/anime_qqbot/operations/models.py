from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class OperatorJobView:
    id: UUID
    job_type: str
    parameters: dict[str, object]
    idempotency_key: str
    status: str
    available_at: datetime
    lease_owner: str | None
    leased_at: datetime | None
    attempt_count: int
    result_summary: dict[str, object] | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class AuditEventView:
    id: UUID
    actor: str
    action: str
    target_type: str
    target_id: str | None
    before_summary: dict[str, object] | None
    after_summary: dict[str, object] | None
    result: str
    error_summary: str | None
    created_at: datetime
