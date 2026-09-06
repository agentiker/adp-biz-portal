#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: postgres-backup-drill.sh --database-url URL [options]

Run a reversible PostgreSQL backup and restore drill in an isolated schema.

Options:
  --database-url URL  PostgreSQL connection URL (required)
  --artifact-dir DIR  Directory for the dump and evidence JSON
  --media-dir DIR     Separate directory that receives the backup copy
  --schema NAME       Scratch schema name (default: generated)
EOF
}

database_url="${DATABASE_URL:-}"
artifact_dir="${DR_ARTIFACT_DIR:-output/tests/m4-dr-01}"
media_dir="${DR_MEDIA_DIR:-}"
schema_name="${DR_SCHEMA:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --database-url)
      database_url="${2:?missing value for --database-url}"
      shift 2
      ;;
    --artifact-dir)
      artifact_dir="${2:?missing value for --artifact-dir}"
      shift 2
      ;;
    --media-dir)
      media_dir="${2:?missing value for --media-dir}"
      shift 2
      ;;
    --schema)
      schema_name="${2:?missing value for --schema}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$database_url" ]]; then
  echo "--database-url or DATABASE_URL is required" >&2
  usage >&2
  exit 2
fi

# pg_dump/pg_restore use the libpq URL scheme. The application uses the
# asyncpg SQLAlchemy scheme, so accept both forms for operator convenience.
if [[ "$database_url" == postgresql+asyncpg://* ]]; then
  pg_database_url="postgresql://${database_url#postgresql+asyncpg://}"
else
  pg_database_url="$database_url"
fi

if [[ -z "$schema_name" ]]; then
  schema_name="m4_drill_$(date -u +%Y%m%d%H%M%S)_$$"
fi

if [[ ! "$schema_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "schema name must contain only letters, digits, and underscores: $schema_name" >&2
  exit 2
fi

if [[ -z "$media_dir" ]]; then
  media_dir="$artifact_dir/independent-media"
fi

mkdir -p "$artifact_dir" "$media_dir"
dump_file="$artifact_dir/platform-backup.dump"
media_dump_file="$media_dir/platform-backup.dump"
evidence_file="$artifact_dir/evidence.json"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
started_epoch_ms="$(python3 -c 'import time; print(time.time_ns() // 1_000_000)')"
schema_created=0

cleanup() {
  if [[ "$schema_created" == "1" ]]; then
    psql "$pg_database_url" -v ON_ERROR_STOP=1 \
      -c "DROP SCHEMA IF EXISTS \"$schema_name\" CASCADE" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "$(psql "$pg_database_url" -Atqc "SELECT 1 FROM pg_namespace WHERE nspname = '$schema_name'")" == "1" ]]; then
  echo "scratch schema already exists: $schema_name" >&2
  exit 1
fi

schema_created=1
psql "$pg_database_url" -v ON_ERROR_STOP=1 -v schema_name="$schema_name" <<'SQL'
CREATE SCHEMA :"schema_name";
CREATE TABLE :"schema_name".platform_backup_marker (
  marker_id text PRIMARY KEY,
  captured_at timestamptz NOT NULL,
  payload jsonb NOT NULL
);
INSERT INTO :"schema_name".platform_backup_marker(marker_id, captured_at, payload)
VALUES (
  'm4-dr-01-marker',
  clock_timestamp(),
  jsonb_build_object('schema', :'schema_name', 'purpose', 'isolated backup restore drill')
);
SQL

before_count="$(psql "$pg_database_url" -Atqc "SELECT count(*) FROM \"$schema_name\".platform_backup_marker")"
pg_dump --format=custom --no-owner --no-privileges --schema="$schema_name" \
  --file="$dump_file" "$pg_database_url"
cp "$dump_file" "$media_dump_file"

checksum="$(shasum -a 256 "$dump_file" | awk '{print $1}')"
media_checksum="$(shasum -a 256 "$media_dump_file" | awk '{print $1}')"
if [[ "$checksum" != "$media_checksum" ]]; then
  echo "backup copy checksum mismatch" >&2
  exit 1
fi

psql "$pg_database_url" -v ON_ERROR_STOP=1 \
  -c "DROP SCHEMA \"$schema_name\" CASCADE"
pg_restore --format=custom --no-owner --no-privileges --exit-on-error \
  --dbname="$pg_database_url" "$media_dump_file"

after_count="$(psql "$pg_database_url" -Atqc "SELECT count(*) FROM \"$schema_name\".platform_backup_marker")"
marker_payload="$(psql "$pg_database_url" -Atqc "SELECT payload::text FROM \"$schema_name\".platform_backup_marker WHERE marker_id = 'm4-dr-01-marker'")"
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
finished_epoch_ms="$(python3 -c 'import time; print(time.time_ns() // 1_000_000)')"
restore_elapsed_ms=$((finished_epoch_ms - started_epoch_ms))

if [[ "$before_count" != "$after_count" || "$after_count" != "1" ]]; then
  echo "restored marker validation failed: before=$before_count after=$after_count" >&2
  exit 1
fi

jq -n \
  --arg scope "M4-DR-01 local PostgreSQL backup and restore drill" \
  --arg startedAt "$started_at" \
  --arg finishedAt "$finished_at" \
  --arg schema "$schema_name" \
  --arg dump "$dump_file" \
  --arg mediaDump "$media_dump_file" \
  --arg checksum "$checksum" \
  --arg mediaChecksum "$media_checksum" \
  --arg markerPayload "$marker_payload" \
  --argjson beforeCount "$before_count" \
  --argjson afterCount "$after_count" \
  --argjson restoreElapsedMs "$restore_elapsed_ms" \
  '{
    scope: $scope,
    startedAt: $startedAt,
    finishedAt: $finishedAt,
    scratchSchema: $schema,
    backupFile: $dump,
    independentMediaCopy: $mediaDump,
    backupSha256: $checksum,
    independentMediaSha256: $mediaChecksum,
    markerRowsBeforeDrop: $beforeCount,
    markerRowsAfterRestore: $afterCount,
    restoreElapsedMs: $restoreElapsedMs,
    restoreElapsedSeconds: ($restoreElapsedMs / 1000),
    rpoObservedSeconds: null,
    rpoTarget: "24h POC daily snapshot; production interval requires business approval",
    storageBoundary: "separate local directory only; this is not off-host or off-site storage",
    markerPayload: $markerPayload,
    result: "passed",
    productionFollowUps: [
      "copy encrypted backup to an independent off-host or object-storage location",
      "schedule backups and measure the approved RPO window",
      "repeat restore against an isolated production-like database and record RTO"
    ]
  }' >"$evidence_file"

echo "backup restore drill passed"
echo "evidence: $evidence_file"
echo "restore elapsed milliseconds: $restore_elapsed_ms"
