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
    PlatformAdpApp,
    AdpAppStatus,
    PlatformAuditEvent,
    PlatformAuthSession,
    PlatformChannelCredential,
    PlatformChannelCursor,
    PlatformChannelIdentity,
    PlatformChannelIdentityStatus,
    PlatformChannelReplayMarker,
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
    PlatformSharedResult,
    PlatformToolCall,
    PlatformToolDefinition,
    PlatformUser,
    EnterpriseExternalAccount,
    IntegrationConnection,
)


MIGRATION_LOCK_KEY = "adp-biz-portal-schema-migration"
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

    CURRENT_PLATFORM_SCHEMA_VERSION = 16
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
        MigrationRevision(
            10,
            "platform_channel_scope_schema",
            (),
        ),
        MigrationRevision(11, "platform_channel_identity_scope_schema", ()),
        MigrationRevision(
            12,
            "platform_channel_execution_scope_schema",
            (PlatformChannelReplayMarker.__tablename__,),
        ),
        MigrationRevision(
            13,
            "platform_shared_result_schema",
            (PlatformSharedResult.__tablename__,),
        ),
        MigrationRevision(
            14,
            "platform_channel_cursor_schema",
            (PlatformChannelCursor.__tablename__,),
        ),
        MigrationRevision(
            15,
            "platform_enterprise_contact_schema",
            (),
        ),
        MigrationRevision(
            16,
            "platform_adp_app_schema",
            (PlatformAdpApp.__tablename__,),
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
            PlatformChannelReplayMarker,
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
            PlatformSharedResult,
            PlatformChannelCursor,
            PlatformAdpApp,
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
    async def _apply_revision_10(cls, db: AsyncSession) -> None:
        """Make channel credentials platform-owned without losing old data silently.

        Revision 8 allowed the same channel instance to be repeated per enterprise.
        A platform-owned instance cannot represent that ambiguity, so migration
        stops with an actionable error instead of choosing a credential. Existing
        ownership metadata is cleared only after the duplicate check succeeds.
        """
        table = PlatformChannelCredential.__tablename__
        await db.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "EnterpriseId" DROP NOT NULL'))
        await db.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "ConnectionId" DROP NOT NULL'))

        duplicates = (
            await db.execute(
                text(
                    f'SELECT "Channel", "ChannelInstanceId", COUNT(*) AS "count" '
                    f'FROM "{table}" '
                    f'GROUP BY "Channel", "ChannelInstanceId" '
                    f'HAVING COUNT(*) > 1 '
                    f'ORDER BY "Channel", "ChannelInstanceId"'
                )
            )
        ).all()
        if duplicates:
            sample = ", ".join(
                f"{channel}/{instance} ({count} rows)"
                for channel, instance, count in duplicates[:5]
            )
            suffix = "" if len(duplicates) <= 5 else f"; and {len(duplicates) - 5} more"
            raise MigrationError(
                "Cannot make channel credentials platform-owned because duplicate "
                f"channel instances require manual merge: {sample}{suffix}"
            )

        # New routing never uses enterprise or connection ownership. Clearing
        # these legacy references also prevents stale deletes from affecting a
        # platform credential after the foreign keys are changed to SET NULL.
        await db.execute(
            text(
                f'UPDATE "{table}" SET "EnterpriseId" = NULL, "ConnectionId" = NULL '
                f'WHERE "EnterpriseId" IS NOT NULL OR "ConnectionId" IS NOT NULL'
            )
        )

        foreign_keys = (
            await db.execute(
                text(
                    "SELECT DISTINCT tc.constraint_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "  ON tc.constraint_schema = kcu.constraint_schema "
                    " AND tc.constraint_name = kcu.constraint_name "
                    "WHERE tc.table_schema = current_schema() "
                    "  AND tc.table_name = :table_name "
                    "  AND tc.constraint_type = 'FOREIGN KEY' "
                    "  AND kcu.column_name IN ('EnterpriseId', 'ConnectionId')"
                ),
                {"table_name": table},
            )
        ).scalars().all()
        for constraint_name in foreign_keys:
            quoted_name = str(constraint_name).replace('"', '""')
            await db.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{quoted_name}"'))

        await db.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "unique_platform_channel_credential"'))
        await db.execute(text(f'DROP INDEX IF EXISTS "idx_platform_channel_credential_lookup"'))
        await db.execute(text(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "unique_platform_channel_credential" '
            f'UNIQUE ("Channel", "ChannelInstanceId")'
        ))
        await db.execute(text(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "fk_platform_channel_credential_enterprise" '
            f'FOREIGN KEY ("EnterpriseId") REFERENCES "{PlatformEnterprise.__tablename__}" ("Id") ON DELETE SET NULL'
        ))
        await db.execute(text(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "fk_platform_channel_credential_connection" '
            f'FOREIGN KEY ("ConnectionId") REFERENCES "{IntegrationConnection.__tablename__}" ("Id") ON DELETE SET NULL'
        ))
        await db.execute(text(
            f'CREATE INDEX "idx_platform_channel_credential_lookup" '
            f'ON "{table}" ("Channel", "ChannelInstanceId", "Status")'
        ))

    @classmethod
    async def _apply_revision_11(cls, db: AsyncSession) -> None:
        """Make channel identities platform-user scoped.

        Existing enterprise scope is legacy metadata only. Clear it so a
        channel identity cannot retain stale authorization after membership
        changes; the worker resolves enterprise scope at execution time.
        """
        table = PlatformChannelIdentity.__tablename__
        await db.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "EnterpriseId" DROP NOT NULL'))
        await db.execute(
            text(f'UPDATE "{table}" SET "EnterpriseId" = NULL WHERE "EnterpriseId" IS NOT NULL')
        )
        foreign_keys = (
            await db.execute(
                text(
                    "SELECT DISTINCT tc.constraint_name "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "  ON tc.constraint_schema = kcu.constraint_schema "
                    " AND tc.constraint_name = kcu.constraint_name "
                    "WHERE tc.table_schema = current_schema() "
                    "  AND tc.table_name = :table_name "
                    "  AND tc.constraint_type = 'FOREIGN KEY' "
                    "  AND kcu.column_name = 'EnterpriseId'"
                ),
                {"table_name": table},
            )
        ).scalars().all()
        for constraint_name in foreign_keys:
            quoted_name = str(constraint_name).replace('"', '""')
            await db.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{quoted_name}"'))
        await db.execute(text(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "fk_platform_channel_identity_enterprise" '
            f'FOREIGN KEY ("EnterpriseId") REFERENCES "{PlatformEnterprise.__tablename__}" ("Id") ON DELETE SET NULL'
        ))

    @classmethod
    async def _apply_revision_12(cls, db: AsyncSession) -> None:
        """Separate channel authorization from browser sessions and close races.

        A channel message is authorized by a confirmed channel identity plus the
        memberships resolved for that message, so its execution context has no
        browser session. Account-wide revocation still invalidates it. The
        partial unique index makes "one active platform user per external
        identity" a database invariant instead of an application-only check.
        """
        execution_table = PlatformExecutionContext.__tablename__
        await db.execute(
            text(f'ALTER TABLE "{execution_table}" ALTER COLUMN "PlatformSessionId" DROP NOT NULL')
        )

        identity_table = PlatformChannelIdentity.__tablename__
        await db.execute(
            text(f'ALTER TABLE "{identity_table}" ALTER COLUMN "ExternalIdentityId" DROP NOT NULL')
        )

        inbound_table = PlatformInboundMessage.__tablename__
        await db.execute(
            text(f'ALTER TABLE "{inbound_table}" ADD COLUMN IF NOT EXISTS "ReplyWindowExpiresAt" TIMESTAMP')
        )

        active = str(PlatformChannelIdentityStatus.ACTIVE)
        duplicates = (
            await db.execute(
                text(
                    f'SELECT "Channel", "ChannelInstanceId", COUNT(*) AS "count" '
                    f'FROM "{identity_table}" '
                    f'WHERE "Status" = :active AND "ExternalIdentityId" IS NOT NULL '
                    f'GROUP BY "Channel", "ChannelInstanceId", "ExternalIdentityId" '
                    f'HAVING COUNT(*) > 1 '
                    f'ORDER BY "Channel", "ChannelInstanceId"'
                ),
                {"active": active},
            )
        ).all()
        if duplicates:
            # The external identity itself is deliberately not reported; the
            # channel instance is enough to locate the rows for a manual merge.
            sample = ", ".join(
                f"{channel}/{instance} ({count} rows)"
                for channel, instance, count in duplicates[:5]
            )
            suffix = "" if len(duplicates) <= 5 else f"; and {len(duplicates) - 5} more"
            raise MigrationError(
                "Cannot enforce a single active platform user per channel identity "
                f"because duplicate active bindings require manual revocation: {sample}{suffix}"
            )
        await db.execute(
            text(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_platform_channel_identity_active" '
                f'ON "{identity_table}" ("Channel", "ChannelInstanceId", "ExternalIdentityId") '
                f"WHERE \"Status\" = '{active}'"
            )
        )

    @classmethod
    async def _apply_revision_15(cls, db: AsyncSession) -> None:
        """Add enterprise contact/identity fields.

        社会统一识别码 (UnifiedSocialCreditCode) is unique when present — a legal
        entity identifier should not be shared — so a partial unique index is used
        rather than a plain UNIQUE constraint (many enterprises may leave it empty
        during backfill). Contact person/phone are free-form optional columns.
        """
        enterprise_table = PlatformEnterprise.__tablename__
        await db.execute(
            text(f'ALTER TABLE "{enterprise_table}" ADD COLUMN IF NOT EXISTS "UnifiedSocialCreditCode" VARCHAR(32)')
        )
        await db.execute(
            text(f'ALTER TABLE "{enterprise_table}" ADD COLUMN IF NOT EXISTS "ContactPerson" VARCHAR(128)')
        )
        await db.execute(
            text(f'ALTER TABLE "{enterprise_table}" ADD COLUMN IF NOT EXISTS "ContactPhone" VARCHAR(32)')
        )
        await db.execute(
            text(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_platform_enterprise_uscc" '
                f'ON "{enterprise_table}" ("UnifiedSocialCreditCode") '
                f'WHERE "UnifiedSocialCreditCode" IS NOT NULL'
            )
        )

    @classmethod
    async def _apply_revision_16(cls, db: AsyncSession) -> None:
        """Add the configurable ADP-app registry and bind enterprises to it.

        ``platform_adp_app`` is created from metadata by the revision's table
        list; here we add the enterprise -> app column (nullable = use default),
        its FK (added by ALTER so a fresh create of platform_enterprise does not
        depend on platform_adp_app existing first), and a partial unique index so
        at most one active row is the default.
        """
        enterprise_table = PlatformEnterprise.__tablename__
        adp_table = PlatformAdpApp.__tablename__
        await db.execute(
            text(f'ALTER TABLE "{enterprise_table}" ADD COLUMN IF NOT EXISTS "AdpAppId" UUID')
        )
        await db.execute(
            text(
                f'CREATE INDEX IF NOT EXISTS "ix_{enterprise_table}_AdpAppId" '
                f'ON "{enterprise_table}" ("AdpAppId")'
            )
        )
        # Add the FK only if it is not already present (idempotent on re-run).
        await db.execute(
            text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_platform_enterprise_adp_app') THEN "
                f'ALTER TABLE "{enterprise_table}" ADD CONSTRAINT "fk_platform_enterprise_adp_app" '
                f'FOREIGN KEY ("AdpAppId") REFERENCES "{adp_table}" ("Id") ON DELETE SET NULL; '
                "END IF; END $$;"
            )
        )
        await db.execute(
            text(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_platform_adp_app_default" '
                f'ON "{adp_table}" ("IsDefault") '
                f"WHERE \"IsDefault\" = true AND \"Status\" = '{str(AdpAppStatus.ACTIVE)}'"
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
                if revision.version == 10:
                    await cls._apply_revision_10(db)
                elif revision.version == 11:
                    await cls._apply_revision_11(db)
                elif revision.version == 12:
                    await cls._apply_revision_12(db)
                elif revision.version == 15:
                    await cls._apply_revision_15(db)
                elif revision.version == 16:
                    await cls._apply_revision_16(db)
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
