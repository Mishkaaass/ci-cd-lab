#!/usr/bin/env bash
# Viewer-only mode. Does not start Docker, kind or Kubernetes operations.
# Serves using project .venv; doctor/token stay read-only when no venv exists.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
case "${1:-serve}" in
  help|-h|--help)
    printf 'Usage: bash scripts/unified-console.sh [serve|doctor|token]\n'
    exit 0
    ;;
  serve)
    bash scripts/setup-venv.sh
    exec "$ROOT/.venv/bin/python" -m unified_console.server serve
    ;;
  doctor|token)
    if [[ -x "$ROOT/.venv/bin/python" ]]; then
      PYTHON_BIN="$ROOT/.venv/bin/python"
    else
      PYTHON_BIN="$(command -v python3.14 || command -v python3 || true)"
    fi
    [[ -n "$PYTHON_BIN" ]] || {
      echo '[BLOCK] Python 3.11+ is required. See make requirements.' >&2
      exit 2
    }
    "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,11)' || {
      echo '[BLOCK] Python 3.11+ is required for read-only diagnostics.' >&2
      exit 2
    }
    exec "$PYTHON_BIN" -m unified_console.server "$1"
    ;;
  *)
    echo 'ERROR: Supported commands are serve, doctor, token' >&2
    exit 2
    ;;
esac
