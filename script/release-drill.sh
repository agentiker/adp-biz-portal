#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
artifact_dir="${RELEASE_DRILL_ARTIFACT_DIR:-$ROOT_DIR/output/tests/m4-release-01}"
database_url="${PLATFORM_TEST_DATABASE_URL:-}"

usage() {
  cat <<'EOF'
Usage: release-drill.sh

Run the local release validation checks without touching the development schema.

Required environment:
  PLATFORM_TEST_DATABASE_URL  PostgreSQL URL used by the isolated-schema migration test

Optional environment:
  RELEASE_DRILL_ARTIFACT_DIR  Directory for logs and evidence JSON
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "$database_url" ]]; then
  echo "PLATFORM_TEST_DATABASE_URL is required" >&2
  usage >&2
  exit 2
fi

mkdir -p "$artifact_dir"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
started_epoch_ms="$(python3 -c 'import time; print(time.time_ns() // 1_000_000)')"
compose_log="$artifact_dir/compose-config.txt"
migration_log="$artifact_dir/migration-drill.txt"
cli_log="$artifact_dir/migration-cli-help.txt"
evidence_file="$artifact_dir/evidence.json"

compose_status="passed"
if ! COMPOSE_ENV_FILE="$ROOT_DIR/docker/.env.example" \
  docker compose --env-file "$ROOT_DIR/docker/.env.example" config >"$compose_log" 2>&1; then
  compose_status="failed"
fi

cli_status="passed"
if ! "$ROOT_DIR/backend/.venv/bin/python" "$ROOT_DIR/backend/migrate.py" --help >"$cli_log" 2>&1; then
  cli_status="failed"
fi

migration_status="passed"
if ! (
  cd "$ROOT_DIR"
  PLATFORM_TEST_DATABASE_URL="$database_url" \
    backend/.venv/bin/pytest backend/test/integration/test_platform_migration_postgres.py -q -s
) >"$migration_log" 2>&1; then
  migration_status="failed"
fi

finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
finished_epoch_ms="$(python3 -c 'import time; print(time.time_ns() // 1_000_000)')"
elapsed_ms=$((finished_epoch_ms - started_epoch_ms))
revision="$(git -C "$ROOT_DIR" rev-parse --verify HEAD 2>/dev/null || printf 'working-tree')"
overall_status="passed"
if [[ "$compose_status" != "passed" || "$cli_status" != "passed" || "$migration_status" != "passed" ]]; then
  overall_status="failed"
fi

python3 - "$evidence_file" "$started_at" "$finished_at" "$elapsed_ms" "$revision" \
  "$compose_status" "$cli_status" "$migration_status" "$compose_log" "$cli_log" "$migration_log" <<'PY'
import json
import sys
from pathlib import Path

(
    evidence_path,
    started_at,
    finished_at,
    elapsed_ms,
    revision,
    compose_status,
    cli_status,
    migration_status,
    compose_log,
    cli_log,
    migration_log,
) = sys.argv[1:]

statuses = {
    "composeConfig": compose_status,
    "migrationCli": cli_status,
    "isolatedMigrationDrill": migration_status,
}
result = "passed" if all(value == "passed" for value in statuses.values()) else "failed"
payload = {
    "scope": "M4-RELEASE-01 local release validation",
    "startedAt": started_at,
    "finishedAt": finished_at,
    "elapsedMs": int(elapsed_ms),
    "releaseRevision": revision,
    "checks": statuses,
    "artifacts": {
        "composeConfig": compose_log,
        "migrationCliHelp": cli_log,
        "migrationDrill": migration_log,
    },
    "migrationDrillBoundary": {
        "database": "isolated PostgreSQL schema created by test fixture",
        "exercise": "upgrade 1..current, repeat upgrade, downgrade to 3, upgrade again",
        "developmentSchemaTouched": False,
    },
    "productionStatus": "not_executed",
    "productionFollowUps": [
        "run the same flow with the deployment identity and approved backup location",
        "record application rollback and health-check timestamps in the release ticket",
        "record production restore RPO/RTO after an isolated restore drill",
    ],
    "result": result,
}
Path(evidence_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "release validation: $overall_status"
echo "evidence: $evidence_file"

if [[ "$overall_status" != "passed" ]]; then
  exit 1
fi
