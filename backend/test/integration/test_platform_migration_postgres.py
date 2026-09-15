from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.migration import Migration, MigrationError
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    PlatformChannelIdentity,
    PlatformChannelIdentityStatus,
    PlatformEnterprise,
    PlatformMigration,
    PlatformRole,
    PlatformStatus,
    PlatformUser,
)


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


@pytest.mark.asyncio
async def test_revision_11_clears_legacy_identity_enterprise_scope(migration_sessionmaker):
    account_id = uuid.uuid4()
    user_id = uuid.uuid4()
    enterprise_id = uuid.uuid4()
    identity_id = uuid.uuid4()

    async with migration_sessionmaker() as db:
        assert await Migration.upgrade(
            db,
            target_version=10,
            applied_by="identity-scope-postgres-test",
        ) == 10
        db.add_all([
            Account(
                Id=account_id,
                Name="Legacy Identity Account",
                Role=AccountRole.NORMAL,
                Status=AccountStatus.ACTIVE,
            ),
            PlatformEnterprise(
                Id=enterprise_id,
                Name="Legacy Identity Enterprise",
                CustomerCode="LEGACY-IDENTITY-SCOPE",
            ),
        ])
        await db.flush()
        db.add(
            PlatformUser(
                Id=user_id,
                AccountId=account_id,
                Name="Legacy Identity User",
                PhoneNormalized="13900000011",
                PhoneMasked="139****0011",
                Role=PlatformRole.CUSTOMER,
                Status=PlatformStatus.ACTIVE,
            )
        )
        await db.flush()
        db.add(
            PlatformChannelIdentity(
                Id=identity_id,
                UserId=user_id,
                AccountId=account_id,
                EnterpriseId=enterprise_id,
                Channel="wechat_official_account",
                ChannelInstanceId="legacy-oa",
                ExternalIdentityId="legacy-openid",
                Status=PlatformChannelIdentityStatus.ACTIVE,
            )
        )
        await db.commit()

        # A fresh revision-10 test database is created from current metadata.
        # Recreate the former production constraint so this exercises the
        # actual NOT NULL + ON DELETE CASCADE upgrade path.
        legacy_foreign_keys = (
            await db.execute(
                text(
                    "SELECT DISTINCT tc.constraint_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "  ON tc.constraint_schema = kcu.constraint_schema "
                    " AND tc.constraint_name = kcu.constraint_name "
                    "WHERE tc.table_schema = current_schema() "
                    "  AND tc.table_name = 'platform_channel_identity' "
                    "  AND tc.constraint_type = 'FOREIGN KEY' "
                    "  AND kcu.column_name = 'EnterpriseId'"
                )
            )
        ).scalars().all()
        for constraint_name in legacy_foreign_keys:
            quoted_name = str(constraint_name).replace('"', '""')
            await db.execute(
                text(
                    'ALTER TABLE "platform_channel_identity" '
                    f'DROP CONSTRAINT "{quoted_name}"'
                )
            )
        await db.execute(
            text(
                'ALTER TABLE "platform_channel_identity" '
                'ALTER COLUMN "EnterpriseId" SET NOT NULL'
            )
        )
        await db.execute(
            text(
                'ALTER TABLE "platform_channel_identity" '
                'ADD CONSTRAINT "legacy_channel_identity_enterprise" '
                'FOREIGN KEY ("EnterpriseId") REFERENCES "platform_enterprise" ("Id") '
                'ON DELETE CASCADE'
            )
        )
        await db.commit()

        assert await Migration.upgrade(
            db,
            applied_by="identity-scope-postgres-test",
        ) == Migration.CURRENT_PLATFORM_SCHEMA_VERSION
        identity = await db.get(PlatformChannelIdentity, identity_id)
        nullable = await db.scalar(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'platform_channel_identity' "
                "AND column_name = 'EnterpriseId'"
            )
        )
        delete_rule = await db.scalar(
            text(
                "SELECT rc.delete_rule "
                "FROM information_schema.referential_constraints rc "
                "WHERE rc.constraint_schema = current_schema() "
                "AND rc.constraint_name = 'fk_platform_channel_identity_enterprise'"
            )
        )
        assert identity is not None
        assert identity.EnterpriseId is None
        assert nullable == "YES"
        assert delete_rule == "SET NULL"

    output = Path(__file__).resolve().parents[3] / "output" / "tests" / "m3-identity-01-platform-scope-migration.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "task": "M3-IDENTITY-01",
                "database": "isolated PostgreSQL schema",
                "fromRevision": 10,
                "toRevision": Migration.CURRENT_PLATFORM_SCHEMA_VERSION,
                "legacyEnterpriseIdCleared": True,
                "enterpriseIdNullable": True,
                "enterpriseDeleteRule": "SET NULL",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


async def _seed_identity_user(db, *, suffix: str):
    """Create one account/user pair usable as a channel-identity owner."""
    account_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db.add(
        Account(
            Id=account_id,
            Name=f"Identity Account {suffix}",
            Role=AccountRole.NORMAL,
            Status=AccountStatus.ACTIVE,
        )
    )
    await db.flush()
    db.add(
        PlatformUser(
            Id=user_id,
            AccountId=account_id,
            Name=f"Identity User {suffix}",
            PhoneNormalized=f"139{uuid.uuid4().int % 100_000_000:08d}",
            PhoneMasked="139****0000",
            Role=PlatformRole.CUSTOMER,
            Status=PlatformStatus.ACTIVE,
        )
    )
    await db.flush()
    return account_id, user_id


@pytest.mark.asyncio
async def test_revision_12_separates_channel_execution_from_browser_sessions(migration_sessionmaker):
    async with migration_sessionmaker() as db:
        assert await Migration.upgrade(
            db,
            applied_by="channel-scope-postgres-test",
        ) == Migration.CURRENT_PLATFORM_SCHEMA_VERSION

        session_nullable = await db.scalar(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'platform_execution_context' "
                "AND column_name = 'PlatformSessionId'"
            )
        )
        identity_nullable = await db.scalar(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'platform_channel_identity' "
                "AND column_name = 'ExternalIdentityId'"
            )
        )
        reply_window = await db.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'platform_inbound_message' "
                "AND column_name = 'ReplyWindowExpiresAt'"
            )
        )
        replay_table = await db.scalar(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'platform_channel_replay_marker'"
            )
        )

        # A channel message authorizes through its binding, so its execution
        # context has no browser session to point at.
        assert session_nullable == "YES"
        # A binding awaiting channel confirmation has no identity yet.
        assert identity_nullable == "YES"
        assert reply_window == "timestamp without time zone"
        assert replay_table == "platform_channel_replay_marker"


@pytest.mark.asyncio
async def test_revision_12_enforces_one_active_owner_per_channel_identity(migration_sessionmaker):
    async with migration_sessionmaker() as db:
        assert await Migration.upgrade(
            db,
            applied_by="channel-identity-unique-postgres-test",
        ) == Migration.CURRENT_PLATFORM_SCHEMA_VERSION
        first_account, first_user = await _seed_identity_user(db, suffix="A")
        second_account, second_user = await _seed_identity_user(db, suffix="B")
        db.add(
            PlatformChannelIdentity(
                Id=uuid.uuid4(),
                UserId=first_user,
                AccountId=first_account,
                Channel="wechat_official_account",
                ChannelInstanceId="oa-unique",
                ExternalIdentityId="shared-openid",
                Status=PlatformChannelIdentityStatus.ACTIVE,
            )
        )
        await db.commit()

        # Two platform users must never own the same external identity, even if
        # two confirmations race past the application-level check.
        db.add(
            PlatformChannelIdentity(
                Id=uuid.uuid4(),
                UserId=second_user,
                AccountId=second_account,
                Channel="wechat_official_account",
                ChannelInstanceId="oa-unique",
                ExternalIdentityId="shared-openid",
                Status=PlatformChannelIdentityStatus.ACTIVE,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        # A revoked row keeps no claim, so rebinding after revocation works.
        db.add(
            PlatformChannelIdentity(
                Id=uuid.uuid4(),
                UserId=second_user,
                AccountId=second_account,
                Channel="wechat_official_account",
                ChannelInstanceId="oa-unique",
                ExternalIdentityId="shared-openid",
                Status=PlatformChannelIdentityStatus.REVOKED,
            )
        )
        await db.commit()

        rows = list(
            (
                await db.execute(
                    select(PlatformChannelIdentity).where(
                        PlatformChannelIdentity.ChannelInstanceId == "oa-unique",
                    )
                )
            ).scalars().all()
        )
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_revision_12_rejects_migrating_duplicate_active_bindings(migration_sessionmaker):
    """Duplicates predating the invariant require a decision, not a silent pick."""
    async with migration_sessionmaker() as db:
        assert await Migration.upgrade(
            db,
            target_version=11,
            applied_by="channel-identity-duplicate-postgres-test",
        ) == 11
        # A fresh revision-11 test database is created from current metadata,
        # which already carries the new index. Drop it so this exercises the
        # real upgrade path from a database that predates the invariant.
        await db.execute(text('DROP INDEX IF EXISTS "uq_platform_channel_identity_active"'))
        await db.commit()
        first_account, first_user = await _seed_identity_user(db, suffix="C")
        second_account, second_user = await _seed_identity_user(db, suffix="D")
        db.add_all([
            PlatformChannelIdentity(
                Id=uuid.uuid4(),
                UserId=first_user,
                AccountId=first_account,
                Channel="wechat_official_account",
                ChannelInstanceId="oa-duplicate",
                ExternalIdentityId="duplicate-openid",
                Status=PlatformChannelIdentityStatus.ACTIVE,
            ),
            PlatformChannelIdentity(
                Id=uuid.uuid4(),
                UserId=second_user,
                AccountId=second_account,
                Channel="wechat_official_account",
                ChannelInstanceId="oa-duplicate",
                ExternalIdentityId="duplicate-openid",
                Status=PlatformChannelIdentityStatus.ACTIVE,
            ),
        ])
        await db.commit()

        with pytest.raises(MigrationError, match="manual revocation"):
            await Migration.upgrade(
                db,
                applied_by="channel-identity-duplicate-postgres-test",
            )


@pytest.mark.asyncio
async def test_revision_17_key_upgrade_and_rollback(migration_sessionmaker, monkeypatch):
    from cryptography.fernet import Fernet
    from config import tagentic_config
    monkeypatch.setattr(tagentic_config, "PLATFORM_CHANNEL_CREDENTIAL_KEY", Fernet.generate_key().decode())
    from core.adp_api_key import create_api_key, require_connector_key
    async with migration_sessionmaker() as db:
        await Migration.upgrade(db, target_version=16)
        account_id = uuid.uuid4()
        db.add(Account(Id=account_id, Name="migration sentinel", Role=AccountRole.ADMIN, Status=AccountStatus.ACTIVE))
        await db.commit()
        assert await Migration.upgrade(db) == 18
        _, secret = await create_api_key(db, "migration test")
        await db.commit()
        await require_connector_key(db, secret)
        assert await Migration.downgrade(db, target_version=16, allow_data_loss=True) == 16
        assert await db.get(Account, account_id) is not None
        assert await Migration.upgrade(db) == 18


@pytest.mark.asyncio
async def test_revision_18_preserves_legacy_key(migration_sessionmaker):
    from core.adp_api_key import require_connector_key, reveal_api_key
    from core.error.platform import PlatformBadRequest
    import hashlib
    async with migration_sessionmaker() as db:
        await Migration.upgrade(db, target_version=17)
        await db.execute(text('ALTER TABLE platform_adp_api_key DROP COLUMN IF EXISTS "Ciphertext", DROP COLUMN IF EXISTS "KeyVersion"'))
        secret = 'adp_' + 'x' * 43
        key_id = uuid.uuid4()
        await db.execute(text('INSERT INTO platform_adp_api_key ("Id", "Name", "Prefix", "KeyHash") VALUES (:id, :name, :prefix, :hash)'), {'id':key_id, 'name':'legacy', 'prefix':secret[:12], 'hash':hashlib.sha256(secret.encode()).hexdigest()})
        await db.commit()
        await Migration.upgrade(db)
        assert await require_connector_key(db, secret) == str(key_id)
        with pytest.raises(PlatformBadRequest):
            await reveal_api_key(db, str(key_id))
