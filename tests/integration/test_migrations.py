import asyncio
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL"])
    return config


async def table_names() -> set[str]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
    await engine.dispose()
    return {row[0] for row in rows}


def test_migration_upgrade_downgrade_round_trip() -> None:
    config = alembic_config()

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert {
        "groups",
        "group_members",
        "admin_identities",
        "processed_events",
        "worker_heartbeats",
    }.issubset(asyncio.run(table_names()))

    command.downgrade(config, "base")
    assert "groups" not in asyncio.run(table_names())

    command.upgrade(config, "head")
