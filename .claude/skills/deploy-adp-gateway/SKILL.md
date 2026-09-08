---
name: deploy-adp-gateway
description: >-
  Deploy the ADP gateway (this repo) to the production server xdimspace-01 /
  https://adp.xdimspace.cn. Use when asked to deploy, ship, release, publish,
  push to prod, roll out, roll back, or run a database migration on the
  production instance. Covers building the image locally, shipping it, running
  the compose migration, the reverse-proxy restart, health verification, and
  rollback. Does NOT cover local dev (`script/deploy.sh`, `make dev`).
---

# Deploy the ADP gateway to production

The production instance runs docker-compose at `/opt/tencent-adp-gateway` on the
server reachable via the SSH alias `xdimspace-01`. Public URL is
`https://adp.xdimspace.cn`. This skill is the compose/production path; the local
dev-instance manager `script/deploy.sh` and `make dev` are unrelated.

## Non-negotiable rules (each learned from a real incident)

1. **Never build on the server.** It has ~3.9 GB RAM and **swap = 0**. Running
   `npm`/`make build` there once exhausted memory and took the whole box
   offline — SSH itself stopped answering (banner-exchange timeout) and it
   needed a console reboot. Always build the image locally and ship it.
2. **`.env` is server-side and secret.** Never read it into the transcript,
   never commit it, never overwrite it. Sync source with `git archive`, not
   `rsync --delete` (which would also delete server state and could touch
   `.env`).
3. **Always restart `reverse-proxy` after `compose up`.** nginx resolves the
   `api` upstream IP at start; recreating the `api` container gives it a new IP
   and nginx keeps the old one → `502 Bad Gateway` until the proxy restarts.
4. **Back up the database before any migration**, and keep a rollback image
   tag. Migrations are forward-only in practice; downgrade only with the dump.
5. **Verify with real HTTP + the schema revision**, not just `compose ps`.

## Server facts

- SSH: `ssh xdimspace-01` (user root). Deploy dir `/opt/tencent-adp-gateway`.
- Compose services: `postgres` (17), `migrate` (one-shot), `api`, `worker`,
  `reverse-proxy` (nginx). `api`/`worker` depend on `migrate`
  `service_completed_successfully`, so a failed migration blocks the new
  processes instead of starting them broken.
- DB: database `adp_chat`, user `adp_chat` (both from `.env`). Image arch is
  `amd64` — build with `--platform linux/amd64`.
- Image tag in use: `adp-chat-client:local` (compose reads `APP_IMAGE`, default
  `adp-chat-client:local`).
- Backups live in `/root/adp-backups/`. Rollback tags accumulate as
  `adp-chat-client:rollback-<prevrev>`.

## Preflight (before touching prod, from the repo root, all read-only)

```bash
ssh xdimspace-01 'cd /opt/tencent-adp-gateway && docker compose ps --format "{{.Service}}|{{.Image}}|{{.Status}}"'
ssh xdimspace-01 'cd /opt/tencent-adp-gateway && docker compose exec -T postgres psql -U adp_chat -d adp_chat -tAc "SELECT max(\"Version\") FROM platform_schema_version"'
curl -s -m 15 https://adp.xdimspace.cn/readyz    # note current schemaRevision
```

If a migration is involved, also check the tables it touches are empty/small so
you can state the real data impact (see `docs/operations/release-and-rollback.md`).

## Build locally

Frontend and image both build on your machine. If the client changed:

```bash
cd client && npm run build_app          # writes into server/static/app
cd -
```

Then assemble and build the image:

```bash
make build_server
rsync -aL --exclude='__pycache__' --exclude='.*' build/server/ build/docker/server/
cd build && docker build --platform linux/amd64 --load -t adp-chat-client:<newtag> -f ../docker/Dockerfile . && cd -
```

**Docker Hub is flaky from here.** If `docker build` fails on
`python:3.12-slim` / `node:22-*` with a registry `EOF`, and **no dependency
changed this round** (only source/stdlib), overlay onto the last good image
instead of contacting the registry:

```bash
printf 'FROM adp-chat-client:<lastgoodtag>\nCOPY docker/server /app\n' > build/Dockerfile.overlay
docker build --platform linux/amd64 --load -t adp-chat-client:<newtag> -f build/Dockerfile.overlay build
```

Only valid when `uv.lock`/deps are unchanged — the overlay skips `uv sync`.

Verify the image actually contains the change before shipping (cheap, catches a
stale build):

```bash
docker run --rm --platform linux/amd64 --entrypoint sh adp-chat-client:<newtag> -c \
  'grep -o "CURRENT_PLATFORM_SCHEMA_VERSION = [0-9]*" core/migration.py; python -c "import core.platform_worker; print(\"imports ok\")"'
```

## Ship the image

```bash
docker save adp-chat-client:<newtag> | gzip -1 > /tmp/adp-<newtag>.tar.gz
scp -q /tmp/adp-<newtag>.tar.gz xdimspace-01:/root/
ssh xdimspace-01 'gunzip -c /root/adp-<newtag>.tar.gz | docker load'
```

## Back up the DB (if migrating) and tag rollback

```bash
ssh xdimspace-01 'cd /opt/tencent-adp-gateway && TS=$(date +%Y%m%d%H%M%S) && \
  docker compose exec -T postgres pg_dump -U adp_chat -d adp_chat -Fc > /root/adp-backups/adp_chat-rev<cur>-$TS.dump && \
  docker compose exec -T postgres sh -c "cat > /tmp/v.dump && pg_restore -l /tmp/v.dump | grep -c \"TABLE DATA\"; rm -f /tmp/v.dump" < /root/adp-backups/adp_chat-rev<cur>-$TS.dump'
# tag the image currently in service as the rollback point BEFORE retagging
ssh xdimspace-01 'cd /opt/tencent-adp-gateway && docker tag adp-chat-client:local adp-chat-client:rollback-rev<cur>'
```

`pg_restore -l` must list a non-zero `TABLE DATA` count — that proves the dump is
restorable, not just written.

## Deploy

```bash
ssh xdimspace-01 'cd /opt/tencent-adp-gateway && \
  docker tag adp-chat-client:<newtag> adp-chat-client:local && \
  docker compose up -d && \
  docker compose restart reverse-proxy'
```

`compose up -d` runs the one-shot `migrate` first; `api`/`worker` start only if
it exits 0. The `restart reverse-proxy` is mandatory (rule 3).

## Verify

```bash
curl -s -m 20 https://adp.xdimspace.cn/healthz          # 200
curl -s -m 20 https://adp.xdimspace.cn/readyz           # status ready + expected schemaRevision
ssh xdimspace-01 'cd /opt/tencent-adp-gateway && docker compose logs migrate --since 5m 2>&1 | grep -iE "revision|migration" | tail -5'
ssh xdimspace-01 'cd /opt/tencent-adp-gateway && docker compose logs worker api --since 3m 2>&1 | grep -iE "revision|error|traceback" | tail -8'
```

A pre-existing `[TCADP.get_info] 450006-用户未登录或者未注册` in the api log is a
known ADP metadata-refresh error, unrelated to a deploy — do not treat it as a
failure.

## Rollback

App-only (schema still compatible — the usual case):

```bash
ssh xdimspace-01 'cd /opt/tencent-adp-gateway && \
  docker tag adp-chat-client:rollback-rev<prev> adp-chat-client:local && \
  docker compose up -d && docker compose restart reverse-proxy'
```

DB downgrade only when a revision must be undone and data loss is confirmed
acceptable or restored from the dump — see
`docs/operations/release-and-rollback.md` (`migrate.py downgrade --allow-data-loss`).

## After deploy

- Credentials the customer must enter (e.g. WeChat token/AppSecret/EncodingAESKey)
  are entered by the user in the Admin UI, never handled here.
- Record the deploy in `ROADMAP.md` (date, image tag, schema revision, what
  changed, residual risk), per the repo's CLAUDE.md.
