from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from anime_qqbot.persistence.base import Base


class AnimeSubject(Base):
    __tablename__ = "anime_subjects"

    subject_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title_cn: Mapped[str | None] = mapped_column(String(512))
    title_jp: Mapped[str] = mapped_column(String(512), nullable=False)
    air_date: Mapped[date | None] = mapped_column(Date, index=True)
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
    air_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
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
