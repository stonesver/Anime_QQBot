"""ORM models for the multisource catalog (Task 2).

These tables replace the previous v0.1 cache (anime_subjects / airing_schedules)
starting in v0.2.0. They coexist with the legacy tables until Task 27 drops
them, so an `import` here does not imply the v0.1 cache is gone.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from anime_qqbot.persistence.base import Base, TimestampMixin


class Anime(Base):
    __tablename__ = "animes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    nsfw_flag: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source_links: Mapped[list[AnimeSourceLink]] = relationship(
        back_populates="anime", cascade="all, delete-orphan"
    )
    titles: Mapped[list[AnimeTitle]] = relationship(
        back_populates="anime", cascade="all, delete-orphan"
    )
    airing_occurrences: Mapped[list[AiringOccurrenceRow]] = relationship(
        back_populates="anime", cascade="all, delete-orphan"
    )


class ExternalEntry(Base):
    __tablename__ = "external_entries"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_id", name="uq_external_entries_provider_external_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    snapshots: Mapped[list[SourceSnapshot]] = relationship(
        back_populates="external_entry", cascade="all, delete-orphan"
    )
    source_links: Mapped[list[AnimeSourceLink]] = relationship(
        back_populates="external_entry", cascade="all, delete-orphan"
    )


class AnimeSourceLink(Base):
    __tablename__ = "anime_source_links"
    __table_args__ = (
        UniqueConstraint("anime_id", "external_entry_id", name="uq_anime_source_links_anime_entry"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_anime_source_links_confidence",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    anime_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("animes.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_entry_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("external_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved")
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    anime: Mapped[Anime] = relationship(back_populates="source_links")
    external_entry: Mapped[ExternalEntry] = relationship(back_populates="source_links")


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("external_entry_id", "version", name="uq_source_snapshots_entry_version"),
        CheckConstraint("version >= 1", name="ck_source_snapshots_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    external_entry_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("external_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    external_entry: Mapped[ExternalEntry] = relationship(back_populates="snapshots")


class AnimeTitle(Base):
    __tablename__ = "anime_titles"
    __table_args__ = (
        UniqueConstraint("anime_id", "language", "title", name="uq_anime_titles_anime_lang_title"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    anime_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("animes.id", ondelete="CASCADE"),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    is_alias: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    anime: Mapped[Anime] = relationship(back_populates="titles")


class AiringOccurrenceRow(Base):
    __tablename__ = "airing_occurrences"
    __table_args__ = (
        UniqueConstraint("source_entry_id", "source_event_key", name="uq_airing_occurrences_event"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    anime_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("animes.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_entry_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("external_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    episode_label: Mapped[str] = mapped_column(String(64), nullable=False)
    air_date: Mapped[date] = mapped_column(Date, nullable=False)
    air_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    precision: Mapped[str] = mapped_column(String(16), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(192), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    anime: Mapped[Anime] = relationship(back_populates="airing_occurrences")


class SourceSyncState(Base):
    __tablename__ = "source_sync_states"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_cursor: Mapped[str | None] = mapped_column(String(192))
    rate_limit_remaining: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# Re-export TimestampMixin for downstream models that import from here.
__all__ = [
    "AiringOccurrenceRow",
    "AiringSchedule",  # legacy v0.1
    "Anime",
    "AnimeSourceLink",
    "AnimeSubject",  # legacy v0.1, retained for the duration of the shard
    "AnimeTitle",
    "CatalogSyncState",  # legacy v0.1 (different name from SourceSyncState)
    "ExternalEntry",
    "SourceSnapshot",
    "SourceSyncState",
    "TimestampMixin",
]


# ---------------------------------------------------------------------------
# Legacy v0.1 tables — kept here for ORM coexistence during the shard window.
# Removed in migration 0010 (Task 27).
# ---------------------------------------------------------------------------


class AnimeSubject(Base):
    __tablename__ = "anime_subjects"

    subject_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title_cn: Mapped[str | None] = mapped_column(String(512))
    title_jp: Mapped[str] = mapped_column(String(512), nullable=False)
    air_date: Mapped[date | None] = mapped_column(Date)
    summary: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    total_episodes: Mapped[int | None] = mapped_column(Integer)
    nsfw: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AiringSchedule(Base):
    __tablename__ = "airing_schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("anime_subjects.subject_id", ondelete="CASCADE"), nullable=False
    )
    occurrence_key: Mapped[str] = mapped_column(String(192), unique=True, nullable=False)
    air_date: Mapped[date] = mapped_column(Date, nullable=False)
    air_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    episode: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogSyncState(Base):
    __tablename__ = "catalog_sync_states"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
