"""Migration round-trip tests for the current schema.

Each test wipes the database, runs its scenario, and re-applies
the migrations to ``head`` so that downstream tests can still
connect to a valid schema.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "alembic.ini"
DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test",
)


@pytest.fixture(autouse=True)
def _restore_head() -> None:
    """Always end with the schema at head so the rest of the suite
    continues to find the expected tables.
    """
    yield
    _run_command("head")


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", DB_URL)
    return cfg


def _run_command(target: str) -> None:
    """Upgrade or downgrade to ``target``.

    Use ``+`` prefix to force an upgrade, ``-`` prefix to force a
    downgrade. Without a prefix we try upgrade first, falling back
    to downgrade if the target is at or below the current revision.
    """
    cfg = _alembic_config()
    if target.startswith("+"):
        command.upgrade(cfg, target[1:])
        return
    if target.startswith("-"):
        command.downgrade(cfg, target[1:])
        return
    # Try upgrade; if it raises a RangeNotAncestorError we fall back.
    try:
        command.upgrade(cfg, target)
    except Exception:
        command.downgrade(cfg, target)


def _run(coro):
    return asyncio.run(coro)


async def _drop_public() -> None:
    engine = create_async_engine(DB_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


async def _has_table(name: str) -> bool:
    engine = create_async_engine(DB_URL)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
                    {"n": name},
                )
            ).first()
        return row is not None
    finally:
        await engine.dispose()


async def _has_index(name: str) -> bool:
    engine = create_async_engine(DB_URL)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
                    {"n": name},
                )
            ).first()
        return row is not None
    finally:
        await engine.dispose()


async def _index_for(table: str) -> list[str]:
    engine = create_async_engine(DB_URL)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = :t"),
                    {"t": table},
                )
            ).all()
        return [r[0] for r in rows]
    finally:
        await engine.dispose()


async def _seed_legacy_llm_settings() -> None:
    engine = create_async_engine(DB_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO chat_groups "
                    "(id, platform, external_group_id, timezone, enabled, created_at, updated_at) "
                    "VALUES "
                    "('00000000-0000-0000-0000-000000000101', 'qq', '101', "
                    "'Asia/Shanghai', TRUE, now(), now()), "
                    "('00000000-0000-0000-0000-000000000102', 'qq', '102', "
                    "'Asia/Shanghai', TRUE, now(), now())"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO group_runtime_settings "
                    "(chat_group_id, general_chat_enabled, updated_at) VALUES "
                    "('00000000-0000-0000-0000-000000000101', FALSE, now()), "
                    "('00000000-0000-0000-0000-000000000102', TRUE, now())"
                )
            )
    finally:
        await engine.dispose()


async def _llm_modes() -> list[tuple[str, bool]]:
    engine = create_async_engine(DB_URL)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT llm_mode, llm_image_reply_enabled "
                        "FROM group_runtime_settings ORDER BY chat_group_id"
                    )
                )
            ).all()
        return [(str(row[0]), bool(row[1])) for row in rows]
    finally:
        await engine.dispose()


def test_empty_database_base_to_head() -> None:
    _run(_drop_public())
    _run_command("+head")
    assert not _run(_has_table("anime_subjects"))
    assert _run(_has_table("animes"))
    assert _run(_has_table("follow_subscriptions"))
    assert _run(_has_table("release_batches"))
    assert _run(_has_table("release_batch_items"))
    assert _run(_has_table("mikan_feed_states"))
    assert _run(_has_table("group_runtime_settings"))
    assert _run(_has_table("interaction_sessions"))
    assert _run(_has_table("delivery_controls"))
    assert _run(_has_table("operator_jobs"))
    assert _run(_has_table("admin_audit_events"))
    assert _run(_has_table("runtime_component_states"))
    assert _run(_has_table("runtime_component_events"))
    assert _run(_has_table("content_publications"))
    assert _run(_has_table("content_polls"))
    assert _run(_has_table("content_poll_candidates"))
    assert _run(_has_table("content_poll_votes"))
    assert _run(_has_table("mention_command_policies"))


def test_head_round_trip() -> None:
    _run(_drop_public())
    _run_command("+head")
    _run_command("-base")
    assert not _run(_has_table("animes"))
    assert not _run(_has_table("follow_subscriptions"))
    assert not _run(_has_table("anime_subjects"))
    _run_command("+head")
    assert _run(_has_table("animes"))
    assert not _run(_has_table("anime_subjects"))
    assert _run(_has_table("release_batch_items"))
    assert _run(_has_table("mikan_feed_states"))
    assert _run(_has_table("group_runtime_settings"))
    assert _run(_has_table("interaction_sessions"))
    assert _run(_has_table("delivery_controls"))
    assert _run(_has_table("operator_jobs"))
    assert _run(_has_table("admin_audit_events"))
    assert _run(_has_table("runtime_component_states"))
    assert _run(_has_table("runtime_component_events"))
    assert _run(_has_table("content_publications"))
    assert _run(_has_table("content_polls"))
    assert _run(_has_table("content_poll_candidates"))
    assert _run(_has_table("content_poll_votes"))
    assert _run(_has_table("mention_command_policies"))


def test_0019_preserves_legacy_general_chat_choice() -> None:
    _run(_drop_public())
    _run_command("+0018_minimax_readonly_tools")
    _run(_seed_legacy_llm_settings())

    _run_command("+head")

    assert _run(_llm_modes()) == [("anime_only", True), ("general", True)]


def test_0004_snapshot_forward() -> None:
    _run(_drop_public())
    _run_command("+0004")
    assert _run(_has_table("group_schedules"))
    assert _run(_has_index("ix_notification_jobs_claim"))
    assert _run(_has_index("ix_group_schedules_due"))
    _run_command("+head")
    assert not _run(_has_table("group_schedules"))
    assert not _run(_has_index("ix_notification_jobs_claim"))
    assert not _run(_has_index("ix_group_schedules_due"))
    assert _run(_has_table("follow_subscriptions"))
    assert _run(_has_table("release_batches"))


def test_downgrade_recreates_indexes_and_constraints() -> None:
    _run(_drop_public())
    _run_command("+head")
    # Downgrade to 0006 forces the 0007 downgrade to run, which is the
    # migration responsible for recreating ix_notification_jobs_claim
    # and ix_group_schedules_due.
    _run_command("-0006")
    indexes = _run(_index_for("notification_jobs"))
    assert "ix_notification_jobs_claim" in indexes, f"got {indexes}"
    indexes = _run(_index_for("group_schedules"))
    assert "ix_group_schedules_due" in indexes, f"got {indexes}"
    assert _run(_has_table("notification_jobs"))
    assert _run(_has_table("group_schedules"))
