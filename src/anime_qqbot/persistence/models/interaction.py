"""Persistent group interaction state for the v0.3 gateway."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from anime_qqbot.persistence.base import Base


class GroupRuntimeSetting(Base):
    __tablename__ = "group_runtime_settings"
    __table_args__ = (
        CheckConstraint(
            "(quiet_start_minute IS NULL) = (quiet_end_minute IS NULL)",
            name="ck_group_runtime_settings_quiet_pair",
        ),
        CheckConstraint(
            "quiet_start_minute IS NULL OR quiet_start_minute BETWEEN 0 AND 1439",
            name="ck_group_runtime_settings_quiet_start",
        ),
        CheckConstraint(
            "quiet_end_minute IS NULL OR quiet_end_minute BETWEEN 0 AND 1439",
            name="ck_group_runtime_settings_quiet_end",
        ),
        CheckConstraint("version > 0", name="ck_group_runtime_settings_version"),
    )

    chat_group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mention_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    direct_shortcuts_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    quiet_start_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_end_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_interval_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    proactive_interval_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pause_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InteractionSession(Base):
    __tablename__ = "interaction_sessions"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "external_group_id",
            "external_user_id",
            name="uq_interaction_sessions_scope",
        ),
        CheckConstraint(
            "jsonb_typeof(candidates) = 'array'",
            name="ck_interaction_sessions_candidates_array",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    external_group_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidates: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    result_message_id: Mapped[str | None] = mapped_column(String(192), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["GroupRuntimeSetting", "InteractionSession"]
