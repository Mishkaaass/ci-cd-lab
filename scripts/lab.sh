#!/usr/bin/env bash
# OpsBoard local learning lab. This script never deletes containers, volumes or worktrees.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'STOP: missing command: %s\n' "$1" >&2
    exit 1
  }
}

stop() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}

need python3
need sha256sum

ROOT_ID="$(printf '%s' "$ROOT" | sha256sum | cut -c1-12)"
CONFIG_PARENT="${XDG_CONFIG_HOME:-$HOME/.config}/ci-cd-lab"
LAB_DIR="$CONFIG_PARENT/local-$ROOT_ID"
AUTH_DIR="$LAB_DIR/credentials"
DASHBOARD_URL="http://127.0.0.1:18001"
DEMO_URL="http://127.0.0.1:8080"

usage() {
  cat <<'HELP'
OpsBoard lab - run from the repository root (the directory containing app.py).

  bash scripts/lab.sh start                  Start local dashboard (safe, read-only deployments)
  bash scripts/lab.sh demo                   Start the local Docker blue/green demo
  bash scripts/lab.sh status                 Check dashboard and demo endpoints
  bash scripts/lab.sh tokens                 Show private token FILE PATHS (not their values)
  bash scripts/lab.sh deploy healthy v1 test1   Deploy healthy version to inactive demo slot
  bash scripts/lab.sh deploy broken  v2 test2   Test a broken candidate (traffic should stay put)
  bash scripts/lab.sh rollback               Switch demo traffic back to the prior healthy slot

Use two terminals: leave 'start' running in terminal A; use 'demo' and the
other commands in terminal B. All URLs bind to 127.0.0.1 (this computer only).
No command in this helper deletes Docker volumes or Git worktrees.
HELP
}

show_tokens() {
  [ -s "$AUTH_DIR/auth.json" ] && [ -s "$AUTH_DIR/viewer.token" ] && [ -s "$AUTH_DIR/operator.token" ] || {
    stop "credentials not found for this checkout; run 'bash scripts/lab.sh start' first"
  }
  printf 'Viewer token file:   %s\n' "$AUTH_DIR/viewer.token"
  printf 'Operator token file: %s\n' "$AUTH_DIR/operator.token"
  printf 'To view a token locally: cat "%s"\n' "$AUTH_DIR/viewer.token"
  printf 'Never paste a token into a chat, a screenshot, an issue, or Git.\n'
}

start_dashboard() {
  need python3.14
  [ -f app.py ] && [ -f requirements-dev.txt ] && [ -f scripts/create-security-credentials.py ] || {
    stop "required files not found; get the latest main branch and run from this checkout"
  }
  [ ! -L "$CONFIG_PARENT" ] || stop "configuration directory is a symlink; inspect it before continuing"
  umask 077
  mkdir -p "$CONFIG_PARENT"
  chmod 700 "$CONFIG_PARENT"
  if [ ! -x .venv/bin/python ]; then
    if [ -e .venv ]; then
      stop "an existing .venv is incomplete; preserved, please inspect it"
    fi
    printf '\n[1/3] Creating Python 3.14 environment...\n'
    python3.14 -m venv .venv
  fi
  .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,14), "venv is not Python 3.14"' || {
    stop "the existing .venv uses the wrong Python version; it was not modified"
  }
  printf '\n[2/3] Installing/checking Python dependencies...\n'
  .venv/bin/python -m pip install -q -r requirements-dev.txt
  if [ ! -d "$LAB_DIR" ]; then
    mkdir -m 700 "$LAB_DIR"
  fi
  [ ! -L "$LAB_DIR" ] || stop "lab data directory is a symlink; inspect it before continuing"
  chmod 700 "$LAB_DIR"
  if [ ! -d "$AUTH_DIR" ]; then
    printf '\n[3/3] Creating local private credentials...\n'
    .venv/bin/python scripts/create-security-credentials.py "$AUTH_DIR"
  fi
  [ -s "$AUTH_DIR/auth.json" ] && [ -s "$AUTH_DIR/viewer.token" ] && [ -s "$AUTH_DIR/operator.token" ] || {
    stop "incomplete credential files detected; existing data preserved"
  }
  if [ -L "$AUTH_DIR" ]; then
    stop "credentials directory is a symlink; inspect it before continuing"
  fi
  printf '\nOpen: %s/dashboard\n' "$DASHBOARD_URL"
  printf 'Token files: %s\n' "$AUTH_DIR"
  printf 'Use the viewer or operator token in the Unlock form.\n'
  printf 'Deploy buttons are DISABLED by default; use the safe terminal demo below.\n'
  printf 'Stop this server with Ctrl+C. Your local SQLite data and tokens remain.\n\n'
  export OPSBOARD_AUTH_FILE="$AUTH_DIR/auth.json"
  export DATABASE_URL="sqlite:///$LAB_DIR/opsboard.db"
  export DEMO_SERVICE_URL="$DEMO_URL"
  export OPSBOARD_ALLOWED_HOSTS="127.0.0.1,localhost"
  export OPSBOARD_ENABLE_DEPLOYMENTS=false
  export OPSBOARD_URL="$DASHBOARD_URL"
  exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 18001 \
    --no-access-log --no-server-header --no-proxy-headers
}

# Docker Compose publishes fixed loopback ports. If another stack owns one, stop
# BEFORE creating/replacing containers. Existing containers from this same Compose
# project are accepted, so restarting the demo is idempotent.
check_demo_ports() {
  local port service owner own_id ports_message
  for row in '5432 db' '8001 demo-blue' '8002 demo-green' '8080 nginx'; do
    read -r port service <<< "$row"
    owner="$(sudo docker ps -q --filter "publish=$port")"
    own_id="$(sudo docker compose ps -q "$service")"
    if [ -n "$owner" ]; then
      if [ -z "$own_id" ] || [ "$owner" != "$own_id" ]; then
        printf '\nPort %s is used by another Docker service. Existing containers:\n' "$port" >&2
        sudo docker ps --filter "publish=$port" --format 'table {{.Names}}\t{{.Ports}}' >&2
        stop "port $port conflict; inspect the old service. Nothing has been stopped or removed."
      fi
      continue
    fi
    if ! python3 - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(('127.0.0.1', port))
PY
    then
      stop "port $port is already bound by another local process; run 'sudo ss -ltnp' to inspect it"
    fi
  done
}

start_demo() {
  need sudo
  need curl
  sudo docker info >/dev/null || stop "Docker is unavailable; start Docker Engine and retry"
  sudo docker compose config --quiet || stop "Docker Compose config invalid"
  check_demo_ports
  printf '\nStarting the four local demo services (no volume deletion)...\n'
  sudo docker compose up -d --build db demo-blue demo-green nginx
  sudo docker compose ps
  printf '\nChecking Nginx proxy on %s ...\n' "$DEMO_URL"
  local ok=0
  for _ in $(seq 1 20); do
    if curl -fsS --max-time 3 "$DEMO_URL/ready" >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 1
  done
  [ "$ok" -eq 1 ] || stop "demo not ready; inspect: sudo docker compose logs --tail=50 nginx demo-blue demo-green"
  printf '\nREADY: %s/ready\n' "$DEMO_URL"
  curl -fsS --max-time 5 "$DEMO_URL/version"
  printf '\nOpen the dashboard in terminal A to see the active demo service.\n'
}

status() {
  need curl
  printf '=== OpsBoard dashboard on port 18001 ===\n'
  if ! curl -fsS --max-time 3 "$DASHBOARD_URL/ready"; then
    printf 'Not running/ready (start it with: bash scripts/lab.sh start)\n'
  fi
  printf '\n=== Nginx blue/green demo on port 8080 ===\n'
  if ! curl -fsS --max-time 3 "$DEMO_URL/version"; then
    printf 'Not running/ready (start it with: bash scripts/lab.sh demo)\n'
  fi
  printf '\n'
}

check_local_api() {
  need curl
  [ -s "$AUTH_DIR/operator.token" ] || stop "no operator token for this checkout; run 'start' first"
  curl -fsS --max-time 5 "$DASHBOARD_URL/ready" >/dev/null || {
    stop "OpsBoard is not ready on port 18001; run 'start' in terminal A first"
  }
  # Ensure the responding server has the same operator credential as this checkout.
  python3 - "$AUTH_DIR/operator.token" "$DASHBOARD_URL" <<'PY'
from pathlib import Path
from urllib.request import Request, urlopen
import json, sys
token = Path(sys.argv[1]).read_text().strip()
request = Request(sys.argv[2] + '/api/auth/me', headers={'Authorization': 'Bearer ' + token})
try:
    with urlopen(request, timeout=5) as r:
        data = json.load(r)
        assert data['role'] == 'operator'
except Exception:
    raise SystemExit('STOP: dashboard does not accept the local operator credential; check which checkout is running')
PY
}

demo_deploy() {
  [ "$#" -eq 3 ] || stop "usage: bash scripts/lab.sh deploy healthy|broken VERSION GIT_SHA"
  local mode="$1" version="$2" sha="$3" active target
  [ "$mode" = healthy ] || [ "$mode" = broken ] || stop "mode must be healthy or broken"
  [[ "$version" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || stop "invalid version"
  [[ "$sha" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || stop "invalid Git SHA"
  [ -f nginx/active_backend.inc ] || stop "missing Nginx backend config"
  active="$(sed -n 's/^[[:space:]]*server demo-\(blue\|green\):8000;[[:space:]]*$/\1/p' nginx/active_backend.inc)"
  case "$active" in
    blue) target=green ;;
    green) target=blue ;;
    *) stop "cannot identify the active blue/green slot; no files changed" ;;
  esac
  check_local_api
  export PATH="$ROOT/.venv/bin:$PATH"
  export OPSBOARD_URL="$DASHBOARD_URL"
  export OPSBOARD_RECORD_TOKEN_FILE="$AUTH_DIR/operator.token"
  printf 'Active slot: %s; deploying candidate to inactive slot: %s\n' "$active" "$target"
  printf 'This WILL recreate the inactive demo container and may switch Nginx after checks.\n'
  bash scripts/deploy.sh "$target" "$version" "$sha" "$mode"
}

demo_rollback() {
  check_local_api
  export PATH="$ROOT/.venv/bin:$PATH"
  export OPSBOARD_URL="$DASHBOARD_URL"
  export OPSBOARD_RECORD_TOKEN_FILE="$AUTH_DIR/operator.token"
  printf 'This will switch local Nginx back to the other ready demo slot.\n'
  bash scripts/rollback.sh
}

case "${1:-help}" in
  help|-h|--help)
    usage
    ;;
  start)
    [ "$#" -eq 1 ] || stop "start takes no arguments"
    start_dashboard
    ;;
  demo)
    [ "$#" -eq 1 ] || stop "demo takes no arguments"
    start_demo
    ;;
  status)
    [ "$#" -eq 1 ] || stop "status takes no arguments"
    status
    ;;
  tokens)
    [ "$#" -eq 1 ] || stop "tokens takes no arguments"
    show_tokens
    ;;
  deploy)
    shift
    demo_deploy "$@"
    ;;
  rollback)
    [ "$#" -eq 1 ] || stop "rollback takes no arguments"
    demo_rollback
    ;;
  *)
    stop "unknown command: $1; run 'bash scripts/lab.sh help'"
    ;;
esac
