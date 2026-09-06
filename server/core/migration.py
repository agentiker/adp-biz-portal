"""Explicit, versioned PostgreSQL schema migrations.

The web process only calls :meth:`Migration.validate_startup`. Schema changes
are performed by ``python migrate.py upgrade`` with a deployment identity.
"""

from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.platform import ensure_platform_config, ensure_platform_tools, utc_now
from model.account import Account, AccountThirdParty
from model.agent import AgentConfig
from model.base import Base
from model.chat import ChatConversation, ChatRecord, SharedConversation
from model.platform import (
    PlatformAuditEvent,
    PlatformAuthSession,
    PlatformChannelCredential,
    PlatformChannelIdentity,
    PlatformConfigVersion,
    PlatformConversation,
    PlatformCredential,
    PlatformDeliveryTask,
    PlatformEnterprise,
    PlatformEvidence,
    PlatformExecutionRun,
    PlatformExecutionContext,
    PlatformInboundMessage,
    PlatformMembership,
    PlatformMessage,
    PlatformMigration,
    PlatformSchemaVersion,
    PlatformToolCall,
    PlatformToolDefinition,
    PlatformUser,
    EnterpriseExternalAccount,
    IntegrationConnection,
)


MIGRATION_LOCK_KEY = "adp-chat-client-schema-migration"
MIGRATION_STATUS_APPLIED = "applied"
MIGRATION_STATUS_ROLLED_BACK = "rolled_back"


class MigrationError(RuntimeError):
    """Base error for schema migration failures."""


class MigrationRequiredError(MigrationError):
    """Raised when the application schema is not ready for this release."""


@dataclass(frozen=True)
class MigrationRevision:
    version: int
    name: str
    table_names: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = f"{self.version}:{self.name}:{','.join(self.table_names)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Migration:
    """Versioned migration runner and read-only application startup guard."""

    CURRENT_PLATFORM_SCHEMA_VERSION = 9
    REVISIONS = (
        MigrationRevision(
            1,
            "legacy_chat_schema",
            (
                Account.__tablename__,
                AccountThirdParty.__tablename__,
                ChatConversation.__tablename__,
                ChatRecord.__tablename__,
                SharedConversation.__tablename__,
                AgentConfig.__tablename__,
            ),
        ),
        MigrationRevision(
            2,
            "platform_identity_schema",
            (
                PlatformEnterprise.__tablename__,
                PlatformUser.__tablename__,
                PlatformMembership.__tablename__,
                PlatformCredential.__tablename__,
                PlatformAuthSession.__tablename__,
                PlatformConversation.__tablename__,
            ),
        ),
        MigrationRevision(
            3,
            "platform_delivery_and_config_schema",
            (
                PlatformInboundMessage.__tablename__,
                PlatformDeliveryTask.__tablename__,
                PlatformConfigVersion.__tablename__,
                PlatformSchemaVersion.__tablename__,
            ),
        ),
        MigrationRevision(
            4,
            "platform_execution_and_audit_schema",
            (
                PlatformToolDefinition.__tablename__,
                PlatformExecutionContext.__tablename__,
                PlatformToolCall.__tablename__,
                PlatformAuditEvent.__tablename__,
            ),
        ),
        MigrationRevision(5, "explicit_migration_lifecycle", ()),
        MigrationRevision(
            6,
            "portal_conversation_history_schema",
            (
                PlatformExecutionRun.__tablename__,
                PlatformMessage.__tablename__,
                PlatformEvidence.__tablename__,
            ),
        ),
        MigrationRevision(
            7,
            "legacy_application_binding_schema",
            (
                IntegrationConnection.__tablename__,
                EnterpriseExternalAccount.__tablename__,
            ),
        ),
        MigrationRevision(
            8,
            "platform_channel_credential_schema",
            (PlatformChannelCredential.__tablename__,),
        ),
        MigrationRevision(
            9,
            "platform_channel_identity_binding_schema",
            (PlatformChannelIdentity.__tablename__,),
        ),
    )

    @classmethod
    def tables(cls):
        """Return every managed model for compatibility and diagnostics."""
        return [
            Account,
            AccountThirdParty,
            ChatRecord,
            ChatConversation,
            SharedConversation,
            AgentConfig,
            PlatformEnterprise,
            IntegrationConnection,
            EnterpriseExternalAccount,
            PlatformChannelCredential,
            PlatformChannelIdentity,
            PlatformUser,
            PlatformMembership,
            PlatformCredential,
            PlatformAuthSession,
            PlatformConversation,
            PlatformMessage,
            PlatformExecutionRun,
            PlatformEvidence,
            PlatformInboundMessage,
            PlatformDeliveryTask,
            PlatformConfigVersion,
            PlatformToolDefinition,
            PlatformExecutionContext,
            PlatformToolCall,
            PlatformAuditEvent,
            PlatformSchemaVersion,
            PlatformMigration,
        ]

    @classmethod
    def _revision(cls, version: int) -> MigrationRevision:
        for revision in cls.REVISIONS:
            if revision.version == version:
                return revision
        raise MigrationError(f"Unknown migration revision: {version}")

    @classmethod
    def _validate_target(cls, target_version: int) -> None:
        if not isinstance(target_version, int):
            raise MigrationError("Migration target must be an integer")
        if target_version < 0 or target_version > cls.CURRENT_PLATFORM_SCHEMA_VERSION:
            raise MigrationError(
                f"Migration target must be between 0 and {cls.CURRENT_PLATFORM_SCHEMA_VERSION}"
            )

    @staticmethod
    async def _table_names(db: AsyncSession) -> set[str]:
        current_schema = await db.scalar(text("SELECT current_schema()"))
        names = await db.run_sync(
            lambda sync_session: inspect(sync_session.get_bind()).get_table_names(
                schema=current_schema
            )
        )
        return set(names)

    @classmethod
    async def check_tables(cls, db: AsyncSession) -> list[str]:
        existing = await cls._table_names(db)
        target = [table.name for table in Base.metadata.sorted_tables]
        return [name for name in target if name not in existing]

    @staticmethod
    @asynccontextmanager
    async def _migration_lock(db: AsyncSession):
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": MIGRATION_LOCK_KEY},
        )
        try:
            yield
        except BaseException:
            if db.in_transaction():
                await db.rollback()
            raise
        else:
            if db.in_transaction():
                await db.commit()

    @staticmethod
    async def _create_history_table(db: AsyncSession) -> None:
        if PlatformMigration.__tablename__ not in await Migration._table_names(db):
            await db.run_sync(
                lambda sync_session: PlatformMigration.__table__.create(
                    sync_session.get_bind(),
                    checkfirst=False,
                )
            )

    @classmethod
    async def _records(cls, db: AsyncSession) -> dict[int, PlatformMigration]:
        records = (await db.execute(select(PlatformMigration))).scalars().all()
        result = {record.Version: record for record in records}
        unknown = sorted(version for version in result if version > cls.CURRENT_PLATFORM_SCHEMA_VERSION)
        if unknown:
            raise MigrationError(
                "Database was migrated by a newer application release: "
                + ", ".join(str(version) for version in unknown)
            )
        for version, record in result.items():
            revision = cls._revision(version)
            if record.Checksum != revision.checksum or record.Name != revision.name:
                raise MigrationError(
                    f"Migration revision {version} does not match the application checksum"
                )
        return result

    @classmethod
    def _current_version_from_records(cls, records: dict[int, PlatformMigration]) -> int:
        applied = sorted(
            version
            for version, record in records.items()
            if record.Status == MIGRATION_STATUS_APPLIED
        )
        if not applied:
            return 0
        expected = list(range(1, applied[-1] + 1))
        if applied != expected:
            raise MigrationError(
                f"Migration history is not contiguous: applied={applied}, expected={expected}"
            )
        return applied[-1]

    @classmethod
    async def current_version(cls, db: AsyncSession) -> int:
        if PlatformMigration.__tablename__ not in await cls._table_names(db):
            return 0
        return cls._current_version_from_records(await cls._records(db))

    @classmethod
    async def _create_revision_tables(
        cls,
        db: AsyncSession,
        revision: MigrationRevision,
    ) -> None:
        if not revision.table_names:
            return
        tables = [Base.metadata.tables[name] for name in revision.table_names]
        current_schema = await db.scalar(text("SELECT current_schema()"))
        existing = await db.run_sync(
            lambda sync_session: {
                table.name
                for table in tables
                if inspect(sync_session.get_bind()).has_table(
                    table.name,
                    schema=current_schema,
                )
            }
        )
        for table in tables:
            if table.name in existing:
                continue
            await db.run_sync(
                lambda sync_session, table=table: table.create(
                    sync_session.get_bind(),
                    checkfirst=False,
                )
            )

    @classmethod
    async def _drop_revision_tables(
        cls,
        db: AsyncSession,
        revision: MigrationRevision,
    ) -> None:
        if not revision.table_names:
            return
        tables = [Base.metadata.tables[name] for name in revision.table_names]
        current_schema = await db.scalar(text("SELECT current_schema()"))
        existing = await db.run_sync(
            lambda sync_session: {
                table.name
                for table in tables
                if inspect(sync_session.get_bind()).has_table(
                    table.name,
                    schema=current_schema,
                )
            }
        )
        for table in reversed(tables):
            if table.name not in existing:
                continue
            await db.run_sync(
                lambda sync_session, table=table: table.drop(
                    sync_session.get_bind(),
                    checkfirst=False,
                )
            )

    @classmethod
    async def upgrade(
        cls,
        db: AsyncSession,
        *,
        target_version: int | None = None,
        applied_by: str = "migration-cli",
    ) -> int:
        """Apply pending revisions atomically under the migration lock."""
        target = (
            cls.CURRENT_PLATFORM_SCHEMA_VERSION
            if target_version is None
            else target_version
        )
        cls._validate_target(target)
        actor = (applied_by or "migration-cli").strip()[:128]

        async with cls._migration_lock(db):
            await db.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            await cls._create_history_table(db)
            records = await cls._records(db)
            current = cls._current_version_from_records(records)
            if target < current:
                raise MigrationError(
                    f"Database is at revision {current}; use downgrade for target {target}"
                )

            for revision in cls.REVISIONS:
                if revision.version <= current or revision.version > target:
                    continue
                await cls._create_revision_tables(db, revision)
                record = records.get(revision.version)
                if record is None:
                    record = PlatformMigration(
                        Version=revision.version,
                        Name=revision.name,
                        Checksum=revision.checksum,
                    )
                record.Status = MIGRATION_STATUS_APPLIED
                record.AppliedBy = actor
                record.AppliedAt = utc_now()
                record.RolledBackAt = None
                db.add(record)

                if PlatformSchemaVersion.__tablename__ in await cls._table_names(db):
                    compatibility_version = await db.get(
                        PlatformSchemaVersion,
                        revision.version,
                    )
                    if compatibility_version is None:
                        db.add(PlatformSchemaVersion(Version=revision.version))
                records[revision.version] = record
                logging.info(
                    "Applied database migration %s (%s)",
                    revision.version,
                    revision.name,
                )

            if target == cls.CURRENT_PLATFORM_SCHEMA_VERSION:
                await ensure_platform_tools(db)
                await ensure_platform_config(db)
            return cls._current_version_from_records(await cls._records(db))

    @classmethod
    async def downgrade(
        cls,
        db: AsyncSession,
        *,
        target_version: int,
        applied_by: str = "migration-cli",
        allow_data_loss: bool = False,
    ) -> int:
        """Roll back revisions, requiring an explicit destructive-data flag."""
        cls._validate_target(target_version)
        if not allow_data_loss:
            raise MigrationError(
                "Downgrade drops schema objects and requires allow_data_loss=True"
            )
        actor = (applied_by or "migration-cli").strip()[:128]

        async with cls._migration_lock(db):
            if PlatformMigration.__tablename__ not in await cls._table_names(db):
                raise MigrationError("Migration history table does not exist")
            records = await cls._records(db)
            current = cls._current_version_from_records(records)
            if target_version > current:
                raise MigrationError(
                    f"Database is at revision {current}; use upgrade for target {target_version}"
                )

            for version in range(current, target_version, -1):
                revision = cls._revision(version)
                await cls._drop_revision_tables(db, revision)
                record = records[version]
                record.Status = MIGRATION_STATUS_ROLLED_BACK
                record.AppliedBy = actor
                record.RolledBackAt = utc_now()
                db.add(record)
                logging.warning(
                    "Rolled back database migration %s (%s)",
                    revision.version,
                    revision.name,
                )
            return cls._current_version_from_records(await cls._records(db))

    @classmethod
    async def validate_startup(cls, db: AsyncSession) -> None:
        """Fail closed when a deploy omitted the explicit migration command."""
        table_names = await cls._table_names(db)
        if PlatformMigration.__tablename__ not in table_names:
            raise MigrationRequiredError(
                "Database is not migrated. Run `python migrate.py upgrade` before starting the server."
            )

        current = cls._current_version_from_records(await cls._records(db))
        if current != cls.CURRENT_PLATFORM_SCHEMA_VERSION:
            raise MigrationRequiredError(
                "Database revision "
                f"{current} does not match required revision "
                f"{cls.CURRENT_PLATFORM_SCHEMA_VERSION}. Run `python migrate.py upgrade`."
            )

        missing = await cls.check_tables(db)
        if missing:
            raise MigrationRequiredError(
                "Database migration history is current but managed tables are missing: "
                + ", ".join(missing)
            )
        logging.info("Database schema revision %s is current", current)

    @classmethod
    async def init(cls, db: AsyncSession, app=None) -> None:
        """Compatibility entry point used by existing startup registration."""
        del app
        await cls.validate_startup(db)
