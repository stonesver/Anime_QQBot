"""Persistent application-level group polls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.catalog import Anime
from anime_qqbot.persistence.models.content_operations import (
    ContentPoll,
    ContentPollCandidate,
    ContentPollVote,
)
from anime_qqbot.persistence.models.identity import ChatGroup

POLL_THEMES = {
    "weekly_best": "本周最佳",
    "next_week_anticipated": "下周最期待",
    "season_favorite": "本季度最喜欢",
    "group_watch": "群内共看",
}


@dataclass(frozen=True, slots=True)
class PollCandidateView:
    id: UUID
    anime_id: UUID
    position: int
    title: str
    votes: int


@dataclass(frozen=True, slots=True)
class PollView:
    id: UUID
    external_group_id: str
    theme: str
    theme_label: str
    status: str
    period_key: str
    timezone: str
    opens_at: datetime
    closes_at: datetime
    candidates: tuple[PollCandidateView, ...]

    @property
    def counts(self) -> dict[int, int]:
        return {candidate.position: candidate.votes for candidate in self.candidates}


@dataclass(frozen=True, slots=True)
class VoteResult:
    poll: PollView
    selected_position: int

    @property
    def counts(self) -> dict[int, int]:
        return self.poll.counts


class PollService:
    """Deep module for poll validation, state transitions and aggregate reads."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def open_poll(
        self,
        *,
        chat_group_id: UUID,
        theme: str,
        anime_ids: tuple[UUID, ...],
        period_key: str,
        actor: str,
        opens_at: datetime,
        closes_at: datetime,
    ) -> PollView:
        if theme not in POLL_THEMES:
            raise ValueError("unsupported poll theme")
        unique_ids = tuple(dict.fromkeys(anime_ids))
        if len(unique_ids) < 3 or len(unique_ids) > 6:
            raise ValueError("poll requires 3..6 distinct candidates")
        if opens_at.tzinfo is None or closes_at.tzinfo is None or closes_at <= opens_at:
            raise ValueError("invalid poll window")
        if not period_key or len(period_key) > 128:
            raise ValueError("invalid poll period key")

        poll_id = uuid4()
        async with self._sessions() as session, session.begin():
            group = await session.get(ChatGroup, chat_group_id, with_for_update=True)
            if group is None:
                raise LookupError("group not found")
            current = await session.scalar(
                select(ContentPoll.id).where(
                    ContentPoll.chat_group_id == chat_group_id,
                    ContentPoll.status == "open",
                )
            )
            if current is not None:
                raise ValueError("group already has an open poll")
            rows = (
                (
                    await session.execute(
                        select(Anime).where(
                            Anime.id.in_(unique_ids),
                            Anime.disabled.is_(False),
                            Anime.nsfw_flag != "true",
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_id = {row.id: row for row in rows}
            if set(by_id) != set(unique_ids):
                raise ValueError("poll candidate is missing, disabled, or blocked")
            now = opens_at
            session.add(
                ContentPoll(
                    id=poll_id,
                    chat_group_id=chat_group_id,
                    theme=theme,
                    status="open",
                    period_key=period_key,
                    created_by=actor[:128],
                    opens_at=opens_at,
                    closes_at=closes_at,
                    created_at=now,
                    updated_at=now,
                )
            )
            for position, anime_id in enumerate(unique_ids, start=1):
                session.add(
                    ContentPollCandidate(
                        id=uuid4(),
                        poll_id=poll_id,
                        anime_id=anime_id,
                        position=position,
                    )
                )
        view = await self.get(poll_id)
        assert view is not None
        return view

    async def current(self, *, external_group_id: str, now: datetime) -> PollView | None:
        async with self._sessions() as session:
            poll_id = await session.scalar(
                select(ContentPoll.id)
                .join(ChatGroup, ChatGroup.id == ContentPoll.chat_group_id)
                .where(
                    ChatGroup.platform == "qq",
                    ChatGroup.external_group_id == external_group_id,
                    ContentPoll.status == "open",
                    ContentPoll.opens_at <= now,
                    ContentPoll.closes_at > now,
                )
                .order_by(ContentPoll.opens_at.desc())
                .limit(1)
            )
        return await self.get(poll_id) if poll_id is not None else None

    async def get(self, poll_id: UUID) -> PollView | None:
        async with self._sessions() as session:
            poll_row = (
                await session.execute(
                    select(ContentPoll, ChatGroup)
                    .join(ChatGroup, ChatGroup.id == ContentPoll.chat_group_id)
                    .where(ContentPoll.id == poll_id)
                )
            ).one_or_none()
            if poll_row is None:
                return None
            poll, group = poll_row
            rows = (
                await session.execute(
                    select(
                        ContentPollCandidate,
                        Anime,
                        func.count(ContentPollVote.id),
                    )
                    .join(Anime, Anime.id == ContentPollCandidate.anime_id)
                    .outerjoin(
                        ContentPollVote,
                        ContentPollVote.candidate_id == ContentPollCandidate.id,
                    )
                    .where(ContentPollCandidate.poll_id == poll_id)
                    .group_by(ContentPollCandidate.id, Anime.id)
                    .order_by(ContentPollCandidate.position)
                )
            ).all()
        return PollView(
            id=poll.id,
            external_group_id=group.external_group_id,
            theme=poll.theme,
            theme_label=POLL_THEMES[poll.theme],
            status=poll.status,
            period_key=poll.period_key,
            timezone=group.timezone,
            opens_at=poll.opens_at,
            closes_at=poll.closes_at,
            candidates=tuple(
                PollCandidateView(
                    id=candidate.id,
                    anime_id=anime.id,
                    position=candidate.position,
                    title=anime.display_title or "未命名番剧",
                    votes=int(votes),
                )
                for candidate, anime, votes in rows
            ),
        )

    async def vote(
        self,
        *,
        external_group_id: str,
        external_user_id: str,
        position: int,
        now: datetime,
    ) -> VoteResult:
        if position < 1 or position > 6:
            raise ValueError("invalid poll candidate number")
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    select(ContentPoll, ContentPollCandidate)
                    .join(ChatGroup, ChatGroup.id == ContentPoll.chat_group_id)
                    .join(
                        ContentPollCandidate,
                        ContentPollCandidate.poll_id == ContentPoll.id,
                    )
                    .where(
                        ChatGroup.platform == "qq",
                        ChatGroup.external_group_id == external_group_id,
                        ContentPoll.status == "open",
                        ContentPoll.opens_at <= now,
                        ContentPoll.closes_at > now,
                        ContentPollCandidate.position == position,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                raise ValueError("no open poll or candidate")
            poll, candidate = row
            stmt = (
                pg_insert(ContentPollVote)
                .values(
                    id=uuid4(),
                    poll_id=poll.id,
                    candidate_id=candidate.id,
                    external_user_id=external_user_id[:64],
                    updated_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_content_poll_votes_user",
                    set_={"candidate_id": candidate.id, "updated_at": now},
                )
            )
            await session.execute(stmt)
            poll_id = poll.id
        view = await self.get(poll_id)
        assert view is not None
        return VoteResult(view, position)

    async def cancel_vote(
        self,
        *,
        external_group_id: str,
        external_user_id: str,
        now: datetime,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            poll_id = await session.scalar(
                select(ContentPoll.id)
                .join(ChatGroup, ChatGroup.id == ContentPoll.chat_group_id)
                .where(
                    ChatGroup.platform == "qq",
                    ChatGroup.external_group_id == external_group_id,
                    ContentPoll.status == "open",
                    ContentPoll.opens_at <= now,
                    ContentPoll.closes_at > now,
                )
                .with_for_update()
            )
            if poll_id is None:
                raise ValueError("no open poll")
            result = await session.execute(
                delete(ContentPollVote).where(
                    ContentPollVote.poll_id == poll_id,
                    ContentPollVote.external_user_id == external_user_id[:64],
                )
            )
            return int(getattr(result, "rowcount", 0)) == 1

    async def close_poll(self, poll_id: UUID, *, now: datetime) -> PollView:
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(ContentPoll)
                .where(ContentPoll.id == poll_id, ContentPoll.status == "open")
                .values(status="closed", updated_at=now)
            )
            if int(getattr(result, "rowcount", 0)) != 1:
                raise ValueError("poll is not open")
        view = await self.get(poll_id)
        assert view is not None
        return view


def format_poll(view: PollView) -> str:
    local_closes_at = view.closes_at.astimezone(ZoneInfo(view.timezone))
    lines = [f"📊 {view.theme_label}", f"截止：{local_closes_at:%m-%d %H:%M}", ""]
    lines.extend(
        f"{candidate.position}. {candidate.title} · {candidate.votes} 票"
        for candidate in view.candidates
    )
    lines.extend(["", "发送「/番剧 投票 编号」参与，重复投票会改票。"])
    return "\n".join(lines)


__all__ = [
    "POLL_THEMES",
    "PollCandidateView",
    "PollService",
    "PollView",
    "VoteResult",
    "format_poll",
]
