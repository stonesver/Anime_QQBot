from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from anime_qqbot.persistence.base import Base, TimestampMixin


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_openid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    active_messages_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_group_members_role"),
        UniqueConstraint("group_id", "member_openid", name="uq_group_members_group_member"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    member_openid: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdminIdentity(Base):
    __tablename__ = "admin_identities"
    __table_args__ = (
        UniqueConstraint("group_openid", "member_openid", name="uq_admin_identities_pair"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_openid: Mapped[str] = mapped_column(String(128), nullable=False)
    member_openid: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
