from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.migration import Migration
from model.platform import PlatformMigration


pytestmark = pytest.mark.integration


def _database_url() -> str:
    url = os.getenv("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def migration_sessionmaker():
    database_url = _database_url()
    schema = f"platform_migration_test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url, pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin_engine.dispose()

    engine = create_async_engine(
        database_url,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        cleanup_engine = create_async_engine(database_url, pool_pre_ping=True)
        async with cleanup_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_migrations_are_repeatable_audited_and_reversible(migration_sessionmaker):
    async with migration_sessionmaker() as db:
        first_version = await Migration.upgrade(db, applied_by="postgres-test")
        second_version = await Migration.upgrade(db, applied_by="postgres-test-rerun")
        records = (
            (await db.execute(select(PlatformMigration).order_by(PlatformMigration.Version)))
            .scalars()
            .all()
        )

        assert first_version == Migration.CURRENT_PLATFORM_SCHEMA_VERSION
        assert second_version == first_version
        assert [record.Version for record in records] == list(range(1, Migration.CURRENT_PLATFORM_SCHEMA_VERSION + 1))
        assert all(record.Status == "applied" for record in records)
        assert {record.AppliedBy for record in records} == {"postgres-test"}
        await Migration.validate_startup(db)

        rolled_back = await Migration.downgrade(
            db,
            target_version=3,
            applied_by="postgres-test-rollback",
            allow_data_loss=True,
        )
        assert rolled_back == 3
        assert await Migration.current_version(db) == 3

        upgraded_again = await Migration.upgrade(db, applied_by="postgres-test-reupgrade")
        assert upgraded_again == Migration.CURRENT_PLATFORM_SCHEMA_VERSION
        await Migration.validate_startup(db)
        history = (
            (await db.execute(select(PlatformMigration).order_by(PlatformMigration.Version)))
            .scalars()
            .all()
        )
        assert all(record.Status == "applied" for record in history)

    output = Path(__file__).resolve().parents[3] / "output" / "tests" / "m1-mig-01-migration.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "scope": "M1-MIG-01 versioned database migrations",
                "upgrade": str(Migration.CURRENT_PLATFORM_SCHEMA_VERSION),
                "repeatable": True,
                "auditedRevisions": list(range(1, Migration.CURRENT_PLATFORM_SCHEMA_VERSION + 1)),
                "rollbackTarget": 3,
                "reupgrade": str(Migration.CURRENT_PLATFORM_SCHEMA_VERSION),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
