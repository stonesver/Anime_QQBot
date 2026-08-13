"""Validated global aliases for deterministic @mention commands."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.interaction import MentionCommandPolicyRow

MENTION_ACTIONS = (
    "today",
    "week",
    "search",
    "detail",
    "next",
    "resource_detail",
    "my_subscriptions",
    "subscribe",
    "unsubscribe",
    "help",
)

DEFAULT_MENTION_ALIASES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "today": ("今天播什么", "今天有什么", "今天有什么番", "今日番剧"),
        "week": ("本周播什么", "本周有什么", "本周有什么番", "本周番剧"),
        "search": ("搜番", "搜索", "找番"),
        "detail": ("详情", "看"),
        "next": ("下次",),
        "resource_detail": ("资源详情",),
        "my_subscriptions": ("我的订阅", "我的追番"),
        "subscribe": ("追番", "订阅"),
        "unsubscribe": ("退订", "取消订阅"),
        "help": ("帮助",),
    }
)


class MentionPolicyValidationError(ValueError):
    """The global mention alias set is incomplete, ambiguous, or unsafe."""


class MentionPolicyVersionConflictError(RuntimeError):
    """The global alias policy changed after the caller read it."""


@dataclass(frozen=True)
class MentionCommandPolicy:
    aliases: Mapping[str, tuple[str, ...]]
    version: int = 1
    customized: bool = False

    @classmethod
    def from_mapping(
        cls,
        aliases: Mapping[str, Sequence[str]],
        *,
        version: int = 1,
        customized: bool = True,
    ) -> MentionCommandPolicy:
        unknown = set(aliases) - set(MENTION_ACTIONS)
        missing = set(MENTION_ACTIONS) - set(aliases)
        if unknown or missing:
            raise MentionPolicyValidationError(
                f"mention aliases require exactly {', '.join(MENTION_ACTIONS)}"
            )
        normalized: dict[str, tuple[str, ...]] = {}
        owners: dict[str, str] = {}
        total = 0
        for action in MENTION_ACTIONS:
            values = aliases[action]
            if not isinstance(values, (list, tuple)):
                raise MentionPolicyValidationError(f"{action} aliases must be a list")
            clean = tuple(dict.fromkeys(_normalize(value) for value in values))
            if not clean or any(not value for value in clean):
                raise MentionPolicyValidationError(f"{action} requires at least one alias")
            if len(clean) > 12:
                raise MentionPolicyValidationError(f"{action} supports at most 12 aliases")
            for value in clean:
                if len(value) > 24:
                    raise MentionPolicyValidationError("mention aliases must be 1 to 24 characters")
                owner = owners.get(value)
                if owner is not None and owner != action:
                    raise MentionPolicyValidationError(
                        f"mention alias {value!r} conflicts between {owner} and {action}"
                    )
                owners[value] = action
            normalized[action] = clean
            total += len(clean)
        if total > 96:
            raise MentionPolicyValidationError("mention aliases support at most 96 entries")
        if version < 1:
            raise MentionPolicyValidationError("mention policy version must be positive")
        return cls(MappingProxyType(normalized), version=version, customized=customized)

    def to_mapping(self) -> dict[str, list[str]]:
        return {action: list(self.aliases[action]) for action in MENTION_ACTIONS}


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        raise MentionPolicyValidationError("mention aliases must be strings")
    return re.sub(r"\s+", " ", value.strip())


DEFAULT_MENTION_COMMAND_POLICY = MentionCommandPolicy.from_mapping(
    DEFAULT_MENTION_ALIASES,
    customized=False,
)


class MentionCommandPolicyRepository:
    """Persist one validated alias policy behind a small versioned interface."""

    _KEY = "default"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self) -> MentionCommandPolicy:
        async with self._sessions() as session:
            row = await session.get(MentionCommandPolicyRow, self._KEY)
        if row is None:
            return DEFAULT_MENTION_COMMAND_POLICY
        return MentionCommandPolicy.from_mapping(
            row.aliases,
            version=row.version,
            customized=row.customized,
        )

    async def update(
        self,
        aliases: Mapping[str, Sequence[str]],
        *,
        expected_version: int,
        now: datetime,
    ) -> MentionCommandPolicy:
        desired = MentionCommandPolicy.from_mapping(
            aliases,
            version=expected_version + 1,
            customized=True,
        )
        payload = desired.to_mapping()
        async with self._sessions() as session, session.begin():
            row = await session.get(MentionCommandPolicyRow, self._KEY, with_for_update=True)
            if row is None:
                if expected_version != DEFAULT_MENTION_COMMAND_POLICY.version:
                    raise MentionPolicyVersionConflictError("mention policy version changed")
                result = await session.execute(
                    insert(MentionCommandPolicyRow)
                    .values(
                        key=self._KEY,
                        aliases=payload,
                        customized=True,
                        version=desired.version,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["key"])
                )
                if int(getattr(result, "rowcount", 0)) != 1:
                    raise MentionPolicyVersionConflictError("mention policy version changed")
            else:
                result = await session.execute(
                    update(MentionCommandPolicyRow)
                    .where(
                        MentionCommandPolicyRow.key == self._KEY,
                        MentionCommandPolicyRow.version == expected_version,
                    )
                    .values(
                        aliases=payload,
                        customized=True,
                        version=desired.version,
                        updated_at=now,
                    )
                )
                if int(getattr(result, "rowcount", 0)) != 1:
                    raise MentionPolicyVersionConflictError("mention policy version changed")
        return desired

    async def restore_defaults(
        self,
        *,
        expected_version: int,
        now: datetime,
    ) -> MentionCommandPolicy:
        desired = MentionCommandPolicy.from_mapping(
            DEFAULT_MENTION_ALIASES,
            version=expected_version + 1,
            customized=False,
        )
        payload = desired.to_mapping()
        async with self._sessions() as session, session.begin():
            row = await session.get(MentionCommandPolicyRow, self._KEY, with_for_update=True)
            if row is None:
                if expected_version != DEFAULT_MENTION_COMMAND_POLICY.version:
                    raise MentionPolicyVersionConflictError("mention policy version changed")
                result = await session.execute(
                    insert(MentionCommandPolicyRow)
                    .values(
                        key=self._KEY,
                        aliases=payload,
                        customized=False,
                        version=desired.version,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["key"])
                )
            else:
                result = await session.execute(
                    update(MentionCommandPolicyRow)
                    .where(
                        MentionCommandPolicyRow.key == self._KEY,
                        MentionCommandPolicyRow.version == expected_version,
                    )
                    .values(
                        aliases=payload,
                        customized=False,
                        version=desired.version,
                        updated_at=now,
                    )
                )
            if int(getattr(result, "rowcount", 0)) != 1:
                raise MentionPolicyVersionConflictError("mention policy version changed")
        return desired


__all__ = [
    "DEFAULT_MENTION_ALIASES",
    "DEFAULT_MENTION_COMMAND_POLICY",
    "MENTION_ACTIONS",
    "MentionCommandPolicy",
    "MentionCommandPolicyRepository",
    "MentionPolicyValidationError",
    "MentionPolicyVersionConflictError",
]
