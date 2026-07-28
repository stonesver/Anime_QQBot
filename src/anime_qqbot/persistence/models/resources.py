"""Persistent Mikan feed, release, and batching state."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from anime_qqbot.persistence.base import Base


class MikanFeedState(Base):
    __tablename__ = "mikan_feed_states"

    id: Mapped[str] = mapped_column(String(192), primary_key=True)
    external_entry_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("external_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    rss_url: Mapped[str] = mapped_column(Text, nullable=False)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_poll_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourceRelease(Base):
    __tablename__ = "resource_releases"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    mikan_item_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    content_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    raw_title: Mapped[str] = mapped_column(String(512), nullable=False)
    pub_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_url: Mapped[str | None] = mapped_column(Text)
    episode_label: Mapped[str | None] = mapped_column(String(64))
    subtitle_groups: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    language: Mapped[str | None] = mapped_column(String(16))
    resolutions: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list)
    anime_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("animes.id", ondelete="SET NULL")
    )
    mikan_entry_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("external_entries.id", ondelete="SET NULL")
    )
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReleaseBatch(Base):
    __tablename__ = "release_batches"
    __table_args__ = (
        UniqueConstraint(
            "anime_id",
            "episode_label",
            "window_started_at",
            name="uq_release_batches_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    anime_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("animes.id", ondelete="CASCADE")
    )
    episode_label: Mapped[str] = mapped_column(String(64), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")


class ReleaseBatchItem(Base):
    __tablename__ = "release_batch_items"

    batch_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("release_batches.id", ondelete="CASCADE"),
        primary_key=True,
    )
    release_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resource_releases.id", ondelete="CASCADE"),
        primary_key=True,
        unique=True,
    )


__all__ = [
    "MikanFeedState",
    "ReleaseBatch",
    "ReleaseBatchItem",
    "ResourceRelease",
]
