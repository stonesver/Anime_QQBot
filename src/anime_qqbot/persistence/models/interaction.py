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
        CheckConstraint(
            "weekly_report_weekday BETWEEN 0 AND 6",
            name="ck_group_runtime_settings_weekly_weekday",
        ),
        CheckConstraint(
            "weekly_report_minute BETWEEN 0 AND 1439",
            name="ck_group_runtime_settings_weekly_minute",
        ),
        CheckConstraint(
            "daily_digest_anchor_minute >= 0 AND "
            "daily_digest_anchor_minute < daily_digest_cutoff_minute AND "
            "daily_digest_cutoff_minute <= 1439",
            name="ck_group_runtime_settings_digest_window",
        ),
        CheckConstraint(
            "daily_digest_quiet_minutes >= 1 AND "
            "daily_digest_quiet_minutes <= "
            "daily_digest_cutoff_minute - daily_digest_anchor_minute",
            name="ck_group_runtime_settings_digest_quiet",
        ),
        CheckConstraint(
            "llm_mode IN ('disabled', 'anime_only', 'general')",
            name="ck_group_runtime_settings_llm_mode",
        ),
        CheckConstraint("version > 0", name="ck_group_runtime_settings_version"),
    )

    chat_group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    llm_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="anime_only")
    llm_image_reply_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mention_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    direct_shortcuts_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    weekly_report_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weekly_report_weekday: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weekly_report_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    daily_digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    daily_digest_at_all_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    daily_digest_anchor_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=1350)
    daily_digest_quiet_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    daily_digest_cutoff_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=1410)
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


class MentionCommandPolicyRow(Base):
    __tablename__ = "mention_command_policies"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(aliases) = 'object'",
            name="ck_mention_command_policies_aliases_object",
        ),
        CheckConstraint("version > 0", name="ck_mention_command_policies_version"),
    )

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    aliases: Mapped[dict[str, list[str]]] = mapped_column(JSONB, nullable=False)
    customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["GroupRuntimeSetting", "InteractionSession", "MentionCommandPolicyRow"]
