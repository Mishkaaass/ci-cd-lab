#!/usr/bin/env bash
# One foreground launcher for real local demo services and a guided browser tour.
# No volume deletion, no forceful Docker cleanup, no cloud deployment.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="$(command -v python3.14 || command -v python3)"
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: Python 3.11+ is required" >&2
  exit 1
fi
exec "$PYTHON_BIN" -m unified_console.showcase start
