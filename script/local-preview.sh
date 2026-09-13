#!/usr/bin/env bash
set -euo pipefail
ADP_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ADP_PROJECT_DIR/backend"
exec .venv/bin/sanic app_factory:create_app --factory --single-process --host=127.0.0.1 --port=8000
