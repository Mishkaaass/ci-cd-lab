#!/usr/bin/env bash

set -euo pipefail


SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
)"

REPO_ROOT="$(
    cd "$SCRIPT_DIR/.."
    pwd
)"

cd "$REPO_ROOT"


TARGET="${1:-}"
VERSION="${2:-}"
GIT_SHA="${3:-}"
MODE="${4:-healthy}"

OPSBOARD_URL="${OPSBOARD_URL:-http://127.0.0.1:8000}"
PRODUCTION_URL="${PRODUCTION_URL:-http://127.0.0.1:8080}"
NGINX_CONFIG="nginx/active_backend.inc"


emit_step() {
    local status="$1"
    local name="$2"

    printf \
        'OPSBOARD_STEP|%s|%s\n' \
        "$status" \
        "$name"
}


if [[ -z "$TARGET" || -z "$VERSION" || -z "$GIT_SHA" ]]; then
    echo "Usage:"
    echo "  $0 blue|green VERSION GIT_SHA healthy|broken"
    exit 2
fi


if [[ "$TARGET" != "blue" && "$TARGET" != "green" ]]; then
    echo "ERROR: target must be blue or green"
    exit 2
fi


if [[ "$MODE" != "healthy" && "$MODE" != "broken" ]]; then
    echo "ERROR: mode must be healthy or broken"
    exit 2
fi


ACTIVE_SERVICE=$(
    sed -n \
        's/server demo-\([a-z]*\):8000;/\1/p' \
        "$NGINX_CONFIG"
)


if [[ -z "$ACTIVE_SERVICE" ]]; then
    echo "ERROR: cannot determine active production slot."
    exit 1
fi


if [[ "$ACTIVE_SERVICE" == "$TARGET" ]]; then
    echo "ERROR: $TARGET is currently serving production."
    echo "Deployments are only allowed to the inactive slot."
    exit 1
fi


case "$TARGET" in

    blue)
        SERVICE="demo-blue"
        PORT="8001"
        IMAGE="opsboard-demo:blue-local"
        ;;

    green)
        SERVICE="demo-green"
        PORT="8002"
        IMAGE="opsboard-demo:green-local"
        ;;

esac


START_MS=$(python3 -m opsboard.timing)


record_deployment() {
    local status="$1"
    local duration_ms="$2"

    if ! curl \
        --fail \
        --silent \
        "$OPSBOARD_URL/health" \
        >/dev/null 2>&1
    then
        echo
        echo "WARNING: OpsBoard API unavailable."
        echo "Deployment history was not recorded."
        return 0
    fi

    PAYLOAD=$(
        python3 \
            - "$VERSION" \
            "$GIT_SHA" \
            "$IMAGE" \
            "$status" \
            "$duration_ms" <<'PY'
import json
import sys

version, git_sha, image, status, duration = sys.argv[1:]

print(
    json.dumps(
        {
            "version": version,
            "git_sha": git_sha,
            "image": image,
            "status": status,
            "duration_ms": int(duration),
        }
    )
)
PY
    )

    printf '%s' "$PAYLOAD" | python3 -m opsboard.history || true
}


record_failure() {
    local end_ms
    local duration_ms

    end_ms=$(python3 -m opsboard.timing)
    duration_ms=$((end_ms - START_MS))

    record_deployment \
        "failed" \
        "$duration_ms"
}


restore_previous_backend() {
    echo
    echo "Restoring previous backend: $ACTIVE_SERVICE"

    printf \
        'server demo-%s:8000;\n' \
        "$ACTIVE_SERVICE" \
        > "$NGINX_CONFIG"

    sudo docker compose exec -T nginx nginx -t
    sudo docker compose exec -T nginx nginx -s reload
}


verify_production_release() {
    local expected_version="$1"
    local expected_sha="$2"

    python3 \
        -m opsboard.release_verification \
        --base-url "$PRODUCTION_URL" \
        --version "$expected_version" \
        --git-sha "$expected_sha" \
        --attempts 20 \
        --delay 0.25
}


echo
echo "========================================"
echo " OpsBoard Deployment"
echo "========================================"
echo
echo "Current production : $ACTIVE_SERVICE"
echo "Candidate slot     : $TARGET"
echo "Version            : $VERSION"
echo "Git SHA            : $GIT_SHA"
echo "Mode               : $MODE"
echo


emit_step \
    "success" \
    "Candidate selected"


echo "[1/5] Starting candidate container..."

emit_step \
    "running" \
    "Container started"


if [[ "$TARGET" == "blue" ]]; then

    if ! sudo env \
        BLUE_MODE="$MODE" \
        BLUE_VERSION="$VERSION" \
        BLUE_SHA="$GIT_SHA" \
        docker compose up \
        -d \
        --no-deps \
        --force-recreate \
        "$SERVICE"
    then
        emit_step \
            "failed" \
            "Container started"

        record_failure

        exit 1
    fi

else

    if ! sudo env \
        GREEN_MODE="$MODE" \
        GREEN_VERSION="$VERSION" \
        GREEN_SHA="$GIT_SHA" \
        docker compose up \
        -d \
        --no-deps \
        --force-recreate \
        "$SERVICE"
    then
        emit_step \
            "failed" \
            "Container started"

        record_failure

        exit 1
    fi

fi


emit_step \
    "success" \
    "Container started"


echo
echo "[2/5] Waiting for candidate readiness..."

emit_step \
    "running" \
    "Readiness check"


READY=false

for attempt in {1..15}; do

    if curl \
        --fail \
        --silent \
        "http://127.0.0.1:${PORT}/ready" \
        >/dev/null 2>&1
    then
        READY=true
        break
    fi

    echo "  readiness attempt $attempt/15 failed"
    sleep 1

done


if [[ "$READY" != "true" ]]; then

    emit_step \
        "failed" \
        "Readiness check"

    echo
    echo "========================================"
    echo " DEPLOYMENT FAILED"
    echo "========================================"
    echo
    echo "Candidate failed readiness checks."
    echo "Production traffic was NOT changed."
    echo "Production remains on: $ACTIVE_SERVICE"

    record_failure

    exit 1
fi


emit_step \
    "success" \
    "Readiness check"


echo "Candidate is READY."


emit_step \
    "running" \
    "Release identity verified"


echo
echo "Candidate runtime identity:"

if ! CANDIDATE_JSON=$(
    curl \
        --fail \
        --silent \
        "http://127.0.0.1:${PORT}/version"
)
then
    emit_step \
        "failed" \
        "Release identity verified"

    record_failure

    exit 1
fi


echo "$CANDIDATE_JSON"


if ! CANDIDATE_VERSION=$(
    echo "$CANDIDATE_JSON" |
        python3 -c \
        'import json,sys; print(json.load(sys.stdin)["version"])'
)
then
    emit_step \
        "failed" \
        "Release identity verified"

    record_failure

    exit 1
fi


if ! CANDIDATE_SHA=$(
    echo "$CANDIDATE_JSON" |
        python3 -c \
        'import json,sys; print(json.load(sys.stdin)["git_sha"])'
)
then
    emit_step \
        "failed" \
        "Release identity verified"

    record_failure

    exit 1
fi


if [[ "$CANDIDATE_VERSION" != "$VERSION" || "$CANDIDATE_SHA" != "$GIT_SHA" ]]; then

    emit_step \
        "failed" \
        "Release identity verified"

    echo
    echo "========================================"
    echo " DEPLOYMENT FAILED"
    echo "========================================"
    echo
    echo "Candidate identity does not match requested release."
    echo
    echo "Requested:"
    echo "  Version : $VERSION"
    echo "  SHA     : $GIT_SHA"
    echo
    echo "Running:"
    echo "  Version : $CANDIDATE_VERSION"
    echo "  SHA     : $CANDIDATE_SHA"

    record_failure

    exit 1
fi


emit_step \
    "success" \
    "Release identity verified"


echo
echo "[3/5] Preparing traffic switch..."


emit_step \
    "running" \
    "Nginx configuration validated"


printf \
    'server %s:8000;\n' \
    "$SERVICE" \
    > "$NGINX_CONFIG"


echo
echo "[4/5] Validating and reloading Nginx..."

if ! sudo docker compose exec -T nginx nginx -t; then

    emit_step \
        "failed" \
        "Nginx configuration validated"

    echo
    echo "Nginx configuration validation failed."

    restore_previous_backend
    record_failure

    exit 1
fi


emit_step \
    "success" \
    "Nginx configuration validated"


emit_step \
    "running" \
    "Traffic switched"


if ! sudo docker compose exec -T nginx nginx -s reload; then

    emit_step \
        "failed" \
        "Traffic switched"

    restore_previous_backend
    record_failure

    exit 1
fi


emit_step \
    "success" \
    "Traffic switched"


echo
echo "[5/5] Waiting for production convergence..."

emit_step \
    "running" \
    "Production converged"


if ! verify_production_release \
    "$VERSION" \
    "$GIT_SHA"
then

    emit_step \
        "failed" \
        "Production converged"

    echo
    echo "========================================"
    echo " PRODUCTION VERIFICATION FAILED"
    echo "========================================"
    echo
    echo "Production did not converge to the candidate."
    echo "Automatically restoring previous backend."

    restore_previous_backend
    record_failure

    exit 1
fi


emit_step \
    "success" \
    "Production converged"


END_MS=$(python3 -m opsboard.timing)
DURATION_MS=$((END_MS - START_MS))


record_deployment \
    "success" \
    "$DURATION_MS"


echo
echo "========================================"
echo " DEPLOYMENT SUCCESSFUL"
echo "========================================"
echo
echo "Production slot : $TARGET"
echo "Version         : $VERSION"
echo "Git SHA         : $GIT_SHA"
echo "Duration        : ${DURATION_MS} ms"
echo
