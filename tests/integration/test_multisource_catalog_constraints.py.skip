"""Round-trip and constraint tests for the multisource catalog schema."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


def _alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    return config


def _tables() -> set[str]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])

    async def _run() -> set[str]:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {row[0] for row in rows}

    result = asyncio.run(_run())
    asyncio.run(engine.dispose())
    return result


def test_multisource_tables_present_after_upgrade() -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    names = _tables()
    expected = {
        "animes",
        "external_entries",
        "anime_source_links",
        "source_snapshots",
        "anime_titles",
        "airing_occurrences",
        "source_sync_states",
    }
    assert expected.issubset(names)


def test_old_tables_remain_after_upgrade() -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    names = _tables()
    # v0.1 catalog tables must remain until Task 27 drops them.
    assert "anime_subjects" in names
    assert "airing_schedules" in names


def test_round_trip_base_head_base_head() -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    names = _tables()
    assert "animes" in names
    assert "external_entries" in names


def test_unique_composite_key_on_external_entry() -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])

    async def _exercise() -> None:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO external_entries (id, provider, external_id, url, disabled)
                    VALUES (gen_random_uuid(), 'bangumi', '42', 'https://bgm.tv/subject/42', false)
                    """
                )
            )
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        """
                        INSERT INTO external_entries (id, provider, external_id, url, disabled)
                        VALUES (
                            gen_random_uuid(),
                            'bangumi',
                            '42',
                            'https://bgm.tv/subject/42',
                            false
                        )
                        """
                    )
                )
            assert "unique" in str(excinfo.value).lower()

    asyncio.run(_exercise())
    asyncio.run(engine.dispose())


def test_snapshot_version_unique_per_entry() -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])

    async def _exercise() -> None:
        async with engine.begin() as conn:
            entry_id = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO external_entries (id, provider, external_id)
                        VALUES (gen_random_uuid(), 'anilist', '21') RETURNING id
                        """
                    )
                )
            ).scalar_one()
            await conn.execute(
                text(
                    """
                    INSERT INTO source_snapshots
                        (id, external_entry_id, version, payload, source_time, fetched_at)
                    VALUES (gen_random_uuid(), :eid, 1, '{}'::jsonb, :ts, :ts)
                    """,
                ),
                {"eid": entry_id, "ts": datetime(2026, 7, 15, tzinfo=UTC)},
            )
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        """
                        INSERT INTO source_snapshots
                            (id, external_entry_id, version, payload, source_time, fetched_at)
                        VALUES (gen_random_uuid(), :eid, 1, '{}'::jsonb, :ts, :ts)
                        """,
                    ),
                    {"eid": entry_id, "ts": datetime(2026, 7, 15, tzinfo=UTC)},
                )
            assert "unique" in str(excinfo.value).lower()

    asyncio.run(_exercise())
    asyncio.run(engine.dispose())


def test_source_link_state_column_rejects_unknown_values() -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])

    async def _exercise() -> None:
        async with engine.begin() as conn:
            anime_id = (
                await conn.execute(
                    text(
                        "INSERT INTO animes (id, nsfw_flag, disabled) "
                        "VALUES (gen_random_uuid(), 'unknown', false) RETURNING id"
                    )
                )
            ).scalar_one()
            entry_id = (
                await conn.execute(
                    text(
                        "INSERT INTO external_entries (id, provider, external_id) "
                        "VALUES (gen_random_uuid(), 'bangumi', '99') RETURNING id"
                    )
                )
            ).scalar_one()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO anime_source_links "
                        "(id, anime_id, external_entry_id, status, evidence_type, "
                        "confidence, method, created_at) "
                        "VALUES (gen_random_uuid(), :a, :e, 'fuzzy', 'title_fuzzy', 0.5, 'v1', :ts)"
                    ),
                    {"a": anime_id, "e": entry_id, "ts": datetime(2026, 7, 15, tzinfo=UTC)},
                )

    asyncio.run(_exercise())
    asyncio.run(engine.dispose())


def test_adult_flag_keeps_unknown_state() -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])

    async def _exercise() -> None:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "INSERT INTO animes (id, nsfw_flag, disabled) "
                        "VALUES (gen_random_uuid(), 'unknown', false) RETURNING id, nsfw_flag"
                    )
                )
            ).first()
            assert row is not None
            assert row.nsfw_flag == "unknown"

    asyncio.run(_exercise())
    asyncio.run(engine.dispose())


def test_airing_occurrences_strict_null_for_date_only() -> None:
    config = _alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])

    async def _exercise() -> None:
        async with engine.begin() as conn:
            anime_id = (
                await conn.execute(
                    text(
                        "INSERT INTO animes (id, nsfw_flag, disabled) "
                        "VALUES (gen_random_uuid(), 'unknown', false) RETURNING id"
                    )
                )
            ).scalar_one()
            entry_id = (
                await conn.execute(
                    text(
                        "INSERT INTO external_entries (id, provider, external_id) "
                        "VALUES (gen_random_uuid(), 'bangumi', '7') RETURNING id"
                    )
                )
            ).scalar_one()
            row = (
                await conn.execute(
                    text(
                        "INSERT INTO airing_occurrences "
                        "(id, anime_id, source_entry_id, episode_label, air_date, air_at, "
                        "precision, source_event_key, updated_at) "
                        "VALUES (gen_random_uuid(), :a, :e, '7', :d, NULL, 'date_only', "
                        "'k1', :ts) RETURNING air_at"
                    ),
                    {
                        "a": anime_id,
                        "e": entry_id,
                        "d": date(2026, 7, 15),
                        "ts": datetime(2026, 7, 15, tzinfo=UTC),
                    },
                )
            ).first()
            assert row is not None
            assert row.air_at is None

    asyncio.run(_exercise())
    asyncio.run(engine.dispose())
