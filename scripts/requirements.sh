#!/usr/bin/env bash
# Read-only inventory for the three supported reviewer paths. No downloads,
# sudo, Docker daemon requests, Git mutations or Python package installation.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

echo '=== OPSBOARD / RUN REQUIREMENTS (READ ONLY) ==='
echo
echo '1. Browser / Unified Console (Python standard library; no pip)'
can_run=1
if command -v python3.14 >/dev/null 2>&1 && python3.14 -c 'import sys, venv, ensurepip; assert sys.version_info[:2] == (3,14)' >/dev/null 2>&1; then
  echo '[OK] Python 3.14 with venv support'
elif [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys,venv; assert sys.prefix != sys.base_prefix and sys.version_info[:2] == (3,14)' >/dev/null 2>&1; then
  echo '[OK] Existing project-local Python 3.14 .venv'
else
  echo '[BLOCK] Python 3.14 + venv support missing; install for your user, not via sudo pip'
  can_run=0
fi
if command -v make >/dev/null 2>&1; then echo '[OK] make'; else echo '[INFO] make missing; use bash scripts/setup-venv.sh and bash scripts/showcase.sh'; fi
if command -v git >/dev/null 2>&1; then echo '[OK] Git (needed to clone)'; else echo '[INFO] Git needed only to clone/fetch; ZIP download works too'; fi
if [ -L .venv ]; then
  echo '[BLOCK] .venv is a symlink; inspect it before setup'
  can_run=0
elif [ -x .venv/bin/python ]; then
  echo '[INFO] Project .venv exists; make setup will validate and reuse it'
else
  echo '[INFO] Run make setup to create a local .venv (no PyPI installation)'
fi
echo
echo '2. Docker Blue/Green (adds local containers and ports)'
for cmd in bash curl sha256sum flock sudo; do
  if command -v "$cmd" >/dev/null 2>&1; then echo "[OK] $cmd"; else echo "[INFO] $cmd is missing (needed for some Docker lab operations)"; fi
done
if command -v docker >/dev/null 2>&1; then echo '[OK] Docker CLI found (daemon authorization not tested)'; else echo '[INFO] Docker Engine/Desktop missing'; fi
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then echo '[OK] Docker Compose v2 available'; else echo '[INFO] Docker Compose v2 missing'; fi
echo '[INFO] Check ports 18002, 18001, 8080, 8001, 8002, 5432. Do not kill other listeners.'
echo
echo '3. Kubernetes + Argo CD GitOps (additional optional lab)'
for cmd in kind kubectl; do
  if command -v "$cmd" >/dev/null 2>&1; then echo "[OK] $cmd"; else echo "[INFO] $cmd missing; required only for GitOps"; fi
done
if command -v gh >/dev/null 2>&1; then echo '[OK] GitHub CLI (optional for CI/CD details)'; else echo '[INFO] gh missing; CI/CD details may show Unavailable'; fi
echo '[INFO] Full showcase also needs internet access and sufficient RAM/disk for kind/Argo CD.'
echo
echo '4. Python dependencies'
echo '[INFO] Unified Console + showcase supervisor: Python stdlib, no pip packages.'
echo '[INFO] Legacy FastAPI history API: pinned requirements-dev.txt installed into .venv when started.'
echo '[INFO] Containers install requirements.txt / requirements-demo.txt inside their images.'
echo '[INFO] Local development: make setup-dev explicitly installs requirements-dev.txt into .venv.'
echo
echo '[DONE] Inventory only; no changes made.'
[ "$can_run" -eq 1 ]
