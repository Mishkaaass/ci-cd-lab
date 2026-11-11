#!/usr/bin/env bash
# Disposable, isolated kind + Argo CD demonstration. Never uses the user's kube context.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
umask 077
CLUSTER="opsboard-review"
CONTEXT="kind-$CLUSTER"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/opsboard-gitops-review"
KCFG="$STATE/kubeconfig"
OWNER="$STATE/control-plane-id"
ARGOVERSION="v3.6.1" # A pinned, supported release, not a mutable 'stable' URL.
ARGOMANIFEST="https://raw.githubusercontent.com/argoproj/argo-cd/$ARGOVERSION/manifests/install.yaml"
ORIGINAL_REPO="https://github.com/Mishkaaass/ci-cd-lab.git"

fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Missing $1; see README prerequisites"; }
info() { printf '%s\n' "$*"; }

help() {
  cat <<'HELP'
OpsBoard isolated Kubernetes / Argo CD GitOps lab:
  bash scripts/gitops-demo.sh doctor                 Read-only prerequisites
  bash scripts/gitops-demo.sh up                     Create own kind cluster + Argo CD
  bash scripts/gitops-demo.sh status                 Check Argo sync, Pods and PVC
  bash scripts/gitops-demo.sh ui                     Forward Argo UI to localhost:18080
  bash scripts/gitops-demo.sh app                    Forward OpsBoard to localhost:18081
  bash scripts/gitops-demo.sh drift-test             Test real Argo self-healing
  bash scripts/gitops-demo.sh down --delete-my-lab    Delete ONLY this lab's cluster (PVC lost!)

Public GitHub repo + public GHCR package: no credentials needed.
For private resources, provide dedicated read-only token FILES (never paste tokens in commands):
  GITOPS_READ_TOKEN_FILE=/private/path/token
  GHCR_TOKEN_FILE=/private/path/token GHCR_USERNAME=your-github-user
Override GITOPS_REPO_URL with your HTTPS GitHub fork URL if desired.
No GitOps command modifies local Docker Compose or your default kubeconfig.
HELP
}

# A credential-bearing URL must never be accepted (it leaks into Argo resources/logs).
repo_url() {
  local value="${GITOPS_REPO_URL:-}"
  if [ -z "$value" ]; then
    value="$(git remote get-url origin 2>/dev/null || true)"
  fi
  [ -n "$value" ] || value="$ORIGINAL_REPO"
  if [[ "$value" =~ ^git@github\.com:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(\.git)?$ ]]; then
    value="https://github.com/${BASH_REMATCH[1]}"
  fi
  if [[ ! "$value" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?$ ]]; then
    fail "GitOps source must be an HTTPS GitHub repository URL without credentials"
  fi
  printf '%s\n' "$value"
}

# On restricted Linux installations Docker is available only via interactive sudo.
docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  else
    sudo -n docker "$@"
  fi
}
kind_cmd() {
  local bin
  bin="$(command -v kind)"
  if docker info >/dev/null 2>&1; then
    "$bin" "$@"
  else
    sudo -n "$bin" "$@"
  fi
}
kube() {
  kubectl --kubeconfig "$KCFG" --context "$CONTEXT" "$@"
}

prerequisites() {
  need kind; need kubectl; need docker; need git; need curl; need python3
  if ! docker info >/dev/null 2>&1; then
    need sudo
    sudo -v
    sudo -n docker info >/dev/null 2>&1 || fail "Docker Engine unavailable, even via sudo"
  fi
  local token_file
  for token_file in "${GITOPS_READ_TOKEN_FILE:-}" "${GHCR_TOKEN_FILE:-}"; do
    if [ -n "$token_file" ]; then
      [ -f "$token_file" ] && [ -s "$token_file" ] && [ ! -L "$token_file" ] ||
        fail "Token file is missing, empty or a symlink: $token_file"
    fi
  done
  if [ -n "${GHCR_TOKEN_FILE:-}" ] && [[ ! "${GHCR_USERNAME:-}" =~ ^[A-Za-z0-9-]+$ ]]; then
    fail "Set GHCR_USERNAME to your GitHub username when GHCR_TOKEN_FILE is provided"
  fi
  info "PASS: kind, kubectl and Docker access available"
}

source_access() {
  local remote
  remote="$(repo_url)"
  if [ -z "${GITOPS_READ_TOKEN_FILE:-}" ]; then
    if ! GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false \
      git -c credential.helper= ls-remote "$remote" HEAD >/dev/null 2>&1; then
      fail "Argo cannot access $remote anonymously. Make the repo public or set GITOPS_READ_TOKEN_FILE."
    fi
  fi
  info "PASS: Git source preflight"
  info "GitOps source: $remote"
}

# Compare Docker IDs, not just a cluster name. Never adopt/delete someone else's cluster.
node_id() {
  docker_cmd inspect --format '{{.Id}}' "$CLUSTER-control-plane" 2>/dev/null || true
}
cluster_exists() {
  kind_cmd get clusters 2>/dev/null | grep -Fxq "$CLUSTER"
}
verify_owner() {
  [ -f "$OWNER" ] && [ -s "$OWNER" ] && [ ! -L "$OWNER" ] ||
    fail "No ownership marker for $CLUSTER; will not touch an unknown cluster"
  [ -f "$KCFG" ] && [ ! -L "$KCFG" ] || fail "Missing or unsafe private kubeconfig"
  local actual expected
  actual="$(node_id)"; expected="$(cat "$OWNER")"
  [ -n "$actual" ] && [ "$actual" = "$expected" ] ||
    fail "kind control-plane identity changed; refusing to manage it"
  [ "$(kube config current-context)" = "$CONTEXT" ] ||
    fail "Private kubeconfig context mismatch"
}

prepare_state() {
  [ ! -L "$STATE" ] || fail "State path is a symlink"
  mkdir -p "$STATE"
  chmod 700 "$STATE"
}

# Creates one isolated cluster, owned by this script, with a private kubeconfig.
ensure_cluster() {
  prepare_state
  if cluster_exists; then
    verify_owner
    info "PASS: reusing owned $CLUSTER cluster"
    return
  fi
  [ ! -e "$KCFG" ] || [ -f "$OWNER" ] ||
    fail "A kubeconfig exists without an ownership marker; inspect $STATE"
  kind_cmd create cluster --name "$CLUSTER" --kubeconfig "$KCFG" --wait 180s
  # When kind was run under sudo, the generated file belongs to root.
  if [ ! -r "$KCFG" ]; then
    sudo -n chown "$(id -u):$(id -g)" "$KCFG"
  fi
  chmod 600 "$KCFG"
  local id
  id="$(node_id)"
  [ -n "$id" ] || fail "Cannot identify newly created kind control plane; inspect cluster manually"
  printf '%s\n' "$id" > "$OWNER"
  chmod 600 "$OWNER"
  verify_owner
  info "PASS: isolated Kubernetes cluster $CLUSTER created"
}

prepare_secrets() {
  [ ! -L "$STATE/auth" ] || fail "Auth directory is a symlink"
  if [ ! -d "$STATE/auth" ]; then
    python3 scripts/create-security-credentials.py "$STATE/auth"
  fi
  [ -s "$STATE/auth/auth.json" ] && [ -s "$STATE/auth/viewer.token" ] ||
    fail "Incomplete existing auth data; it was not overwritten"
  if [ ! -d "$STATE/db" ]; then
    mkdir -m 700 "$STATE/db"
    python3 - "$STATE/db" <<'PY'
from pathlib import Path
from urllib.parse import quote
import secrets
import sys

p = Path(sys.argv[1]); password = secrets.token_urlsafe(32)
values = {
    'POSTGRES_DB': 'opsboard',
    'POSTGRES_USER': 'opsboard',
    'POSTGRES_PASSWORD': password,
    'DATABASE_URL': 'postgresql+psycopg://opsboard:' + quote(password, safe='') + '@postgres.opsboard.svc.cluster.local:5432/opsboard',
}
for name, value in values.items():
    file = p / name
    with file.open('x') as out:
        out.write(value)
    file.chmod(0o600)
PY
  fi
  local db_key auth_secret
  for db_key in POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL; do
    [ -s "$STATE/db/$db_key" ] || fail "Incomplete database secret ($db_key); existing data preserved"
  done
  auth_secret="$(grep -Eo 'opsboard-auth-[a-f0-9]{12}' k8s/opsboard/app.yaml | sort -u)"
  [[ "$auth_secret" =~ ^opsboard-auth-[a-f0-9]{12}$ ]] ||
    fail "Unsupported auth Secret reference in Kubernetes manifest"

  kube -n opsboard create secret generic opsboard-db \
    --from-file=POSTGRES_DB="$STATE/db/POSTGRES_DB" \
    --from-file=POSTGRES_USER="$STATE/db/POSTGRES_USER" \
    --from-file=POSTGRES_PASSWORD="$STATE/db/POSTGRES_PASSWORD" \
    --from-file=DATABASE_URL="$STATE/db/DATABASE_URL" \
    --dry-run=client -o yaml | kube -n opsboard apply -f - >/dev/null
  kube -n opsboard create secret generic "$auth_secret" \
    --from-file=auth.json="$STATE/auth/auth.json" \
    --dry-run=client -o yaml | kube -n opsboard apply -f - >/dev/null

  # An empty auths object is correct for a public GHCR image. For private
  # packages, use a separate read:packages token, never an owner/admin token.
  python3 - "$STATE/dockerconfig.json" "${GHCR_USERNAME:-}" "${GHCR_TOKEN_FILE:-}" <<'PY'
import base64
import json
from pathlib import Path
import sys

output = Path(sys.argv[1]); user, token_path = sys.argv[2:]
config = {'auths': {}}
if token_path:
    token = Path(token_path).read_text(encoding='utf-8').strip()
    if not token or any(c.isspace() for c in token):
        raise SystemExit('STOP: invalid GHCR token file')
    auth = base64.b64encode(f'{user}:{token}'.encode()).decode()
    config['auths']['ghcr.io'] = {'auth': auth}
output.write_text(json.dumps(config) + '\n')
output.chmod(0o600)
PY
  kube -n opsboard create secret generic ghcr-pull \
    --type=kubernetes.io/dockerconfigjson \
    --from-file=.dockerconfigjson="$STATE/dockerconfig.json" \
    --dry-run=client -o yaml | kube -n opsboard apply -f - >/dev/null
  info "PASS: private application/database credentials and image pull configuration"
}

prepare_source() {
  local remote
  remote="$(repo_url)"
  printf '%s\n' "$remote" > "$STATE/repo-url"
  if [ -n "${GITOPS_READ_TOKEN_FILE:-}" ]; then
    printf '%s\n' 'x-access-token' > "$STATE/repo-user"
    kube -n argocd create secret generic opsboard-repo \
      --from-literal=type=git \
      --from-file=url="$STATE/repo-url" \
      --from-file=username="$STATE/repo-user" \
      --from-file=password="$GITOPS_READ_TOKEN_FILE" \
      --dry-run=client -o yaml | \
      kube -n argocd apply -f - >/dev/null
    kube -n argocd label secret opsboard-repo \
      argocd.argoproj.io/secret-type=repository --overwrite >/dev/null
  fi
  python3 - "$remote" "$STATE/argo-opsboard.yaml" <<'PY'
from pathlib import Path
import sys

source = Path('k8s/argocd/opsboard.yaml').read_text()
original = 'https://github.com/Mishkaaass/ci-cd-lab.git'
if source.count(original) != 2:
    raise SystemExit('STOP: unexpected Argo CD application source manifest')
Path(sys.argv[2]).write_text(source.replace(original, sys.argv[1]))
PY
  kube -n argocd apply -f "$STATE/argo-opsboard.yaml"
  info "PASS: Argo CD tracks Git main from $remote (not your local worktree)"
}

wait_healthy() {
  local i sync health
  for i in $(seq 1 90); do
    sync="$(kube -n argocd get applications.argoproj.io opsboard \
      -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
    health="$(kube -n argocd get applications.argoproj.io opsboard \
      -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
    if [ "$sync" = Synced ] && [ "$health" = Healthy ]; then
      kube -n opsboard rollout status deployment/opsboard --timeout=30s
      info "PASS: Argo CD Synced / Healthy; Kubernetes Deployment ready"
      return
    fi
    if [ $((i % 12)) -eq 0 ]; then
      info "Waiting for Argo CD: sync=${sync:-unknown}, health=${health:-unknown}"
    fi
    sleep 5
  done
  kube -n argocd get applications.argoproj.io opsboard -o wide || true
  kube -n opsboard get pods,pvc || true
  fail "Argo did not become Synced / Healthy. Check public/private GitHub and GHCR access. No cluster deleted."
}

up() {
  prerequisites
  source_access
  ensure_cluster
  # Explicit kubeconfig/context is used on every kubectl call.
  kube create namespace argocd --dry-run=client -o yaml | kube apply -f - >/dev/null
  kube create namespace opsboard --dry-run=client -o yaml | kube apply -f - >/dev/null
  info "Installing pinned Argo CD $ARGOVERSION in the isolated cluster..."
  curl --fail --silent --show-error --location --retry 3 --max-time 120 \
    "$ARGOMANIFEST" -o "$STATE/argocd-install.yaml"
  kube -n argocd apply --server-side --force-conflicts -f "$STATE/argocd-install.yaml" >/dev/null
  kube -n argocd rollout status deployment/argocd-server --timeout=360s
  kube -n argocd rollout status deployment/argocd-repo-server --timeout=360s
  kube -n argocd rollout status statefulset/argocd-application-controller --timeout=360s
  prepare_secrets
  prepare_source
  wait_healthy
  info "GitOps lab ready. In new terminals run:"
  info "  bash scripts/gitops-demo.sh ui  # https://127.0.0.1:18080"
  info "  bash scripts/gitops-demo.sh app # http://127.0.0.1:18081/dashboard"
}

status() {
  prerequisites
  verify_owner
  info "=== Dedicated cluster: $CONTEXT ==="
  kube get nodes
  info "=== Argo CD ==="
  kube -n argocd get applications.argoproj.io opsboard \
    -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision'
  info "=== Kubernetes runtime and persistent volume ==="
  kube -n opsboard get deployments,pods,pvc
  info "=== Image running in Kubernetes ==="
  kube -n opsboard get deployment opsboard -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
  info "=== Actual running image identities ==="
  kube -n opsboard get pods -l app=opsboard \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[0].imageID}{"\n"}{end}'
}

# Demonstrates genuine self-healing, not a fake status banner. Only an owned kind
# cluster is modified. Any failure restores the expected replica count.
drift_test() {
  prerequisites
  verify_owner
  local sync health replicas
  sync="$(kube -n argocd get applications.argoproj.io opsboard -o jsonpath='{.status.sync.status}')"
  health="$(kube -n argocd get applications.argoproj.io opsboard -o jsonpath='{.status.health.status}')"
  [ "$sync" = Synced ] && [ "$health" = Healthy ] ||
    fail "Application must be Synced/Healthy before a drift test"
  replicas="$(kube -n opsboard get deployment opsboard -o jsonpath='{.spec.replicas}')"
  [ "$replicas" = 1 ] || fail "Unexpected replica baseline $replicas; will not alter it"
  info "Temporarily scaling OpsBoard to 2 replicas. Argo CD should restore Git's 1."
  kube -n opsboard scale deployment/opsboard --replicas=2
  local i current
  for i in $(seq 1 48); do
    current="$(kube -n opsboard get deployment opsboard -o jsonpath='{.spec.replicas}')"
    if [ "$current" = 1 ]; then
      info "PASS: real GitOps self-healing restored replicas=1"
      return
    fi
    sleep 5
  done
  kube -n opsboard scale deployment/opsboard --replicas=1 || true
  fail "Argo did not self-heal within four minutes; requested replicas=1 for safety"
}

down() {
  [ "${2:-}" = --delete-my-lab ] || fail "Destructive: use 'down --delete-my-lab' (deletes this kind cluster and its PVC)"
  prerequisites
  verify_owner
  info "Deleting ONLY $CLUSTER; Kubernetes PVC data in this cluster WILL be lost."
  kind_cmd delete cluster --name "$CLUSTER"
  # Keep private tokens/state for inspection; a future up will start fresh.
  info "Deleted $CLUSTER. Private state in $STATE preserved; no other cluster touched."
}

case "${1:-help}" in
  help|--help|-h) help ;;
  doctor) prerequisites; source_access ;;
  up) up ;;
  status) status ;;
  ui)
    prerequisites; verify_owner
    info 'Argo CD: https://127.0.0.1:18080 (self-signed local certificate).'
    info 'For the local admin password, see the README; never share it.'
    exec kubectl --kubeconfig "$KCFG" --context "$CONTEXT" -n argocd \
      port-forward --address 127.0.0.1 svc/argocd-server 18080:443
    ;;
  app)
    prerequisites; verify_owner
    info 'OpsBoard (Kubernetes): http://127.0.0.1:18081/dashboard'
    info "Viewer token stays private in $STATE/auth/viewer.token"
    exec kubectl --kubeconfig "$KCFG" --context "$CONTEXT" -n opsboard \
      port-forward --address 127.0.0.1 svc/opsboard 18081:80
    ;;
  drift-test) drift_test ;;
  down) down "$@" ;;
  *) fail "Unknown action '$1'; run bash scripts/gitops-demo.sh help" ;;
esac
