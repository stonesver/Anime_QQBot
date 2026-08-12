"""Durable weekly, daily and poll content-operation state."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from anime_qqbot.persistence.base import Base


class ContentPublication(Base):
    __tablename__ = "content_publications"
    __table_args__ = (
        UniqueConstraint(
            "chat_group_id",
            "publication_type",
            "period_key",
            name="uq_content_publications_period",
        ),
        CheckConstraint(
            "publication_type IN "
            "('weekly_report', 'daily_release_digest', 'poll_open', 'poll_result')",
            name="ck_content_publications_type",
        ),
        CheckConstraint(
            "status IN ('planned', 'sent', 'failed', 'unknown')",
            name="ck_content_publications_status",
        ),
        CheckConstraint(
            "essence_status IN ('none', 'set', 'failed', 'removed')",
            name="ck_content_publications_essence",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    chat_group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    publication_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period_key: Mapped[str] = mapped_column(String(128), nullable=False)
    notification_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("notification_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform_message_id: Mapped[str | None] = mapped_column(String(192), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    essence_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentPoll(Base):
    __tablename__ = "content_polls"
    __table_args__ = (
        UniqueConstraint("chat_group_id", "period_key", name="uq_content_polls_period"),
        CheckConstraint(
            "theme IN ('weekly_best', 'next_week_anticipated', 'season_favorite', 'group_watch')",
            name="ck_content_polls_theme",
        ),
        CheckConstraint(
            "status IN ('draft', 'open', 'closed', 'cancelled')",
            name="ck_content_polls_status",
        ),
        CheckConstraint("closes_at > opens_at", name="ck_content_polls_window"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    chat_group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    theme: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    period_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentPollCandidate(Base):
    __tablename__ = "content_poll_candidates"
    __table_args__ = (
        UniqueConstraint("poll_id", "anime_id", name="uq_content_poll_candidates_anime"),
        UniqueConstraint("poll_id", "position", name="uq_content_poll_candidates_position"),
        CheckConstraint("position BETWEEN 1 AND 6", name="ck_content_poll_candidates_position"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    poll_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("content_polls.id", ondelete="CASCADE"),
        nullable=False,
    )
    anime_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("animes.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ContentPollVote(Base):
    __tablename__ = "content_poll_votes"
    __table_args__ = (
        UniqueConstraint("poll_id", "external_user_id", name="uq_content_poll_votes_user"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    poll_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("content_polls.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("content_poll_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "ContentPoll",
    "ContentPollCandidate",
    "ContentPollVote",
    "ContentPublication",
]
