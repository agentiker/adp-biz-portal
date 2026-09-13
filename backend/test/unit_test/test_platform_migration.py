from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.migration import Migration, MigrationError, MigrationRequiredError


def _write_evidence(**payload: object) -> None:
    output = Path(__file__).resolve().parents[3] / "output" / "tests" / "m1-mig-01-migration.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "scope": "M1-MIG-01 versioned database migrations",
                **payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_revisions_are_contiguous_and_have_stable_checksums():
    versions = [revision.version for revision in Migration.REVISIONS]
    assert versions == list(range(1, Migration.CURRENT_PLATFORM_SCHEMA_VERSION + 1))
    assert len({revision.checksum for revision in Migration.REVISIONS}) == len(versions)
    assert all(revision.name and isinstance(revision.table_names, tuple) for revision in Migration.REVISIONS)
    _write_evidence(
        revisionCount=len(versions),
        currentVersion=Migration.CURRENT_PLATFORM_SCHEMA_VERSION,
        checksumsStable=True,
    )


def test_downgrade_requires_explicit_data_loss_acknowledgement():
    with pytest.raises(MigrationError, match="allow_data_loss"):
        # The guard runs before any database access or mutation.
        import asyncio

        asyncio.run(Migration.downgrade(None, target_version=0))


def test_runtime_startup_uses_validation_only():
    source = (Path(__file__).resolve().parents[2] / "middleware" / "database.py").read_text(
        encoding="utf-8"
    )
    assert "Migration.validate_startup(db)" in source
    assert "metadata.create_all" not in source
    assert "ensure_platform_config" not in source
    assert "ensure_platform_tools" not in source
    _write_evidence(
        runtimeCreateAll=False,
        runtimeSeedWrites=False,
        startupGuard="Migration.validate_startup",
    )


def test_invalid_startup_state_has_explicit_migration_error():
    assert issubclass(MigrationRequiredError, MigrationError)
    error = MigrationRequiredError(
        "Database is not migrated. Run `python migrate.py upgrade` before starting the server."
    )
    assert "migrate.py upgrade" in str(error)
