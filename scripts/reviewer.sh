#!/usr/bin/env bash
# Guided, safe reviewer entry point. The web server never receives Docker access.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DEMO_URL="http://127.0.0.1:8080"
DASHBOARD_URL="http://127.0.0.1:18001"

fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Install $1 first"; }

help() {
  cat <<'HELP'
OpsBoard reviewer experience (run from the same checkout in both terminals):
  bash scripts/reviewer.sh doctor       Check local prerequisites
  bash scripts/reviewer.sh dashboard    Terminal A: start the secure web UI
  bash scripts/reviewer.sh up           Terminal B: start the Docker demo
  bash scripts/reviewer.sh status       Check dashboard and Nginx service
  bash scripts/reviewer.sh drill        Broken -> healthy -> rollback (modifies demo)
  bash scripts/reviewer.sh tokens       Show token FILE PATHS (not tokens)

Optional separate Kubernetes lab:
  bash scripts/gitops-demo.sh doctor|up|status|ui|app|drift-test|down
HELP
}

# Only evidence of live Nginx matters; a stale include file is not sufficient.
release() {
  curl --fail --silent --show-error --max-time 5 "$DEMO_URL/version" |
    python3 -c 'import json,sys; x=json.load(sys.stdin); assert x.get("version") and x.get("git_sha"); print(x["version"] + "|" + x["git_sha"])'
}

drill() {
  need flock
  need curl
  need python3
  need date
  # A persistent lock is per checkout, so a second reviewer cannot run concurrently.
  local root_id state lock_file baseline after_broken after_healthy after_rollback stamp
  root_id="$(printf '%s' "$ROOT" | sha256sum | cut -c1-12)"
  state="${XDG_STATE_HOME:-$HOME/.local/state}/opsboard-reviewer/$root_id"
  [ ! -L "$state" ] || fail "Review state path is a symlink"
  umask 077
  mkdir -p "$state"
  chmod 700 "$state"
  lock_file="$state/drill.lock"
  exec 9>"$lock_file"
  flock -n 9 || fail "Another drill is already running from this checkout"

  curl --fail --silent --show-error --max-time 5 "$DASHBOARD_URL/ready" >/dev/null ||
    fail "Start the dashboard in terminal A first: bash scripts/reviewer.sh dashboard"
  # Refuse a stale host include file even when the public endpoint is healthy.
  # The pinned timeout-safe helper verifies Nginx's ACTUAL live release/slot.
  [ -f scripts/nginx_route.py ] || fail "Missing live routing safety helper"
  if ! python3 scripts/nginx_route.py check; then
    fail "Configured route does not match live traffic; inspect before drilling"
  fi
  baseline="$(release)" || fail "Nginx demo is not ready; run bash scripts/reviewer.sh up"
  stamp="$(date -u +%Y%m%d%H%M%S)"
  printf 'Baseline live release: %s\n' "$baseline"

  printf '\n[1/3] Broken candidate: failure is expected\n'
  if bash scripts/lab.sh deploy broken "bad-$stamp" "bad$stamp"; then
    fail "Broken candidate unexpectedly succeeded; stopping without further changes"
  fi
  after_broken="$(release)" || fail "Live service is unavailable after broken candidate"
  [ "$baseline" = "$after_broken" ] || fail "Broken deployment changed live traffic ($baseline -> $after_broken)"
  printf 'PASS: broken candidate rejected; production release unchanged\n'

  printf '\n[2/3] Healthy candidate: validated before switching\n'
  bash scripts/lab.sh deploy healthy "good-$stamp" "good$stamp"
  after_healthy="$(release)" || fail "Live service unavailable after healthy candidate"
  [ "$after_healthy" = "good-$stamp|good$stamp" ] ||
    fail "New live release identity did not match the requested release"
  printf 'PASS: traffic switched to healthy release %s\n' "$after_healthy"

  printf '\n[3/3] Rollback to original healthy slot\n'
  bash scripts/lab.sh rollback
  after_rollback="$(release)" || fail "Live service unavailable after rollback"
  [ "$after_rollback" = "$baseline" ] || fail "Rollback did not restore original release"
  printf '\nPASS: broken gate, healthy rollout, exact rollback identity\n'
  printf 'Live: %s\n' "$after_rollback"
}

case "${1:-help}" in
  help|--help|-h) help ;;
  doctor)
    printf 'Root: %s\n' "$ROOT"
    for tool in bash curl git python3.14 docker; do
      if command -v "$tool" >/dev/null 2>&1; then
        printf 'PASS: %s available\n' "$tool"
      else
        printf 'MISSING: %s\n' "$tool"
      fi
    done
    printf 'Docker Engine/Compose and Python 3.14 are required for the full local demo.\n'
    printf 'kind and kubectl are optional, required only for the GitOps lab.\n'
    ;;
  dashboard) exec bash scripts/lab.sh start ;;
  up) exec bash scripts/lab.sh demo ;;
  status) exec bash scripts/lab.sh status ;;
  tokens) exec bash scripts/lab.sh tokens ;;
  drill) drill ;;
  *) fail "Unknown action '$1' (run bash scripts/reviewer.sh help)" ;;
esac
