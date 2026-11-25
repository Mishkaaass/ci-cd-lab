#!/usr/bin/env bash
# Safe, local Python environment for the reviewer. Default mode uses stdlib
# only. Explicit --dev may download packages into THIS project's .venv.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-}"
if [[ "$MODE" != "" && "$MODE" != "--dev" ]]; then
  echo 'Usage: bash scripts/setup-venv.sh [--dev]' >&2
  exit 2
fi
if [[ -L .venv ]]; then
  echo '[BLOCK] .venv is a symlink. Inspect it; no changes made.' >&2
  exit 2
fi
if [[ -e .venv && ! -x .venv/bin/python ]]; then
  echo '[BLOCK] An incomplete .venv exists. Preserved for inspection; no deletion.' >&2
  exit 2
fi
if [[ ! -x .venv/bin/python ]]; then
  if ! command -v python3.14 >/dev/null 2>&1; then
    echo '[BLOCK] Python 3.14 is required for the OpsBoard full local lab.' >&2
    echo '[INFO] Install a user-scoped Python 3.14, then retry; do not replace system Python.' >&2
    exit 2
  fi
  if ! python3.14 -c 'import sys,venv,ensurepip; assert sys.version_info[:2] == (3,14)' >/dev/null 2>&1; then
    echo '[BLOCK] Python 3.14 or venv/ensurepip support is unavailable.' >&2
    exit 2
  fi
  echo '[SETUP] Creating project-local .venv with Python 3.14.'
  umask 077
  python3.14 -m venv "$ROOT/.venv" || {
    echo '[BLOCK] Could not create .venv. Inspect it before retrying; it was not deleted.' >&2
    exit 2
  }
else
  echo '[REUSE] Existing .venv found.'
fi
.venv/bin/python -c 'import sys,venv; assert sys.prefix != sys.base_prefix and sys.version_info[:2] == (3,14)' || {
  echo '[BLOCK] Existing .venv is incompatible (need isolated Python 3.14); preserved.' >&2
  exit 2
}
echo '[PASS] Python 3.14 isolated in .venv/bin/python.'
if [[ "$MODE" == "--dev" ]]; then
  echo '[INFO] Explicit --dev: installing pinned requirements-dev.txt into .venv (network needed).'
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements-dev.txt
  .venv/bin/python -m pip check
  echo '[PASS] Development dependencies installed only in .venv.'
else
  echo '[INFO] No third-party packages installed by setup; Python standard library is enough for Unified Console.'
fi
