#!/usr/bin/env bash
# Foreground reviewer launcher: Python runs in the project-local .venv;
# only the existing fixed-scope supervisor may request local Docker/GitOps
# changes after a user starts this command. No automatic volume deletion.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
bash scripts/setup-venv.sh
exec "$ROOT/.venv/bin/python" -m unified_console.showcase start
