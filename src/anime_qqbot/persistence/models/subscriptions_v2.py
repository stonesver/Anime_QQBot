"""v0.2 subscription ORM models (Task 16)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from anime_qqbot.persistence.base import Base


class FollowSubscription(Base):
    __tablename__ = "follow_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "chat_group_id",
            "external_user_id",
            "anime_id",
            name="uq_follow_subscriptions_group_user_anime",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    chat_group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("chat_groups.id", ondelete="CASCADE"), nullable=False
    )
    external_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    anime_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("animes.id", ondelete="CASCADE"), nullable=False
    )
    notify_airing: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_resource: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SubscriptionResourceFilter(Base):
    __tablename__ = "subscription_resource_filters"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    subscription_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("follow_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    subtitle_groups: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=[])
    resolutions: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=[])
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
