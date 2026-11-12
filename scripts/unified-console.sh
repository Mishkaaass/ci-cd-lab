#!/usr/bin/env bash
# Unified OpsBoard — local read-only viewer. Does not start/stop Docker or Kubernetes.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="$(command -v python3.14 || command -v python3)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo 'ERROR: Python 3 is required' >&2
  exit 1
fi
case "${1:-serve}" in
  serve|doctor|token) exec "$PYTHON_BIN" -m unified_console.server "${1:-serve}" ;;
  help|-h|--help) printf 'Usage: bash scripts/unified-console.sh [serve|doctor|token]\n';;
  *) echo 'ERROR: Supported commands are serve, doctor, token' >&2; exit 2 ;;
esac
