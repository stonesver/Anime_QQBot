from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from anime_qqbot.persistence.base import Base


class ProcessedPlatformEvent(Base):
    __tablename__ = "processed_platform_events"
    __table_args__ = (
        UniqueConstraint("platform", "event_id", name="uq_processed_events_platform_event"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(192), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    worker_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="worker")


class RuntimeComponentState(Base):
    __tablename__ = "runtime_component_states"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unknown', 'online', 'qq_offline', 'unreachable')",
            name="ck_runtime_component_states_status",
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_runtime_component_states_failures",
        ),
    )

    component_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    offline_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RuntimeComponentEvent(Base):
    __tablename__ = "runtime_component_events"
    __table_args__ = (
        CheckConstraint(
            "previous_status IS NULL OR "
            "previous_status IN ('unknown', 'online', 'qq_offline', 'unreachable')",
            name="ck_runtime_component_events_previous_status",
        ),
        CheckConstraint(
            "status IN ('unknown', 'online', 'qq_offline', 'unreachable')",
            name="ck_runtime_component_events_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    component_name: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runtime_component_states.component_name", ondelete="CASCADE"),
        nullable=False,
    )
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "ProcessedPlatformEvent",
    "RuntimeComponentEvent",
    "RuntimeComponentState",
    "WorkerHeartbeat",
]
