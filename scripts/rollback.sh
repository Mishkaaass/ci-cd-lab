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


CURRENT=$(
    sed -n \
        's/server demo-\([a-z]*\):8000;/\1/p' \
        "$NGINX_CONFIG"
)


# Do not toggle traffic using a stale routing file.
python3 scripts/nginx_route.py check


case "$CURRENT" in

    blue)
        TARGET="green"
        SERVICE="demo-green"
        PORT="8002"
        IMAGE="opsboard-demo:green-local"
        ;;

    green)
        TARGET="blue"
        SERVICE="demo-blue"
        PORT="8001"
        IMAGE="opsboard-demo:blue-local"
        ;;

    *)
        echo "ERROR: cannot determine active production slot."
        exit 1
        ;;

esac


echo
echo "========================================"
echo " OpsBoard Rollback"
echo "========================================"
echo
echo "Current production : $CURRENT"
echo "Rollback target    : $TARGET"
echo


emit_step \
    "success" \
    "Rollback target selected"


emit_step \
    "running" \
    "Target readiness verified"


echo "[1/4] Checking rollback target readiness..."

if ! curl \
    --fail \
    --silent \
    --max-time 4 \
    "http://127.0.0.1:${PORT}/ready" \
    >/dev/null
then
    emit_step \
        "failed" \
        "Target readiness verified"

    echo
    echo "ROLLBACK BLOCKED"
    echo "Previous slot is not ready."

    exit 1
fi


if ! VERSION_JSON=$(
    curl \
        --fail \
        --silent \
        --max-time 4 \
        "http://127.0.0.1:${PORT}/version"
)
then
    emit_step \
        "failed" \
        "Target readiness verified"

    exit 1
fi


if ! VERSION=$(
    echo "$VERSION_JSON" |
        python3 -c \
        'import json,sys; print(json.load(sys.stdin)["version"])'
)
then
    emit_step \
        "failed" \
        "Target readiness verified"

    exit 1
fi


if ! GIT_SHA=$(
    echo "$VERSION_JSON" |
        python3 -c \
        'import json,sys; print(json.load(sys.stdin)["git_sha"])'
)
then
    emit_step \
        "failed" \
        "Target readiness verified"

    exit 1
fi


emit_step \
    "success" \
    "Target readiness verified"


echo "Rollback release:"
echo "$VERSION_JSON"


START_MS=$(python3 -m opsboard.timing)


emit_step \
    "running" \
    "Traffic switched"


echo
echo "[2/4] Validating and switching Nginx (bounded, reversible)..."

if ! python3 scripts/nginx_route.py switch "$TARGET"; then
    emit_step "failed" "Traffic switched"
    exit 1
fi


emit_step \
    "running" \
    "Production converged"


echo
echo "[4/4] Waiting for production convergence..."

if ! python3 \
    -m opsboard.release_verification \
    --base-url "$PRODUCTION_URL" \
    --version "$VERSION" \
    --git-sha "$GIT_SHA" \
    --attempts 20 \
    --delay 0.25
then
    emit_step \
        "failed" \
        "Production converged"

    echo
    echo "ROLLBACK VERIFICATION FAILED"
    echo "Restoring original production slot: $CURRENT"
    python3 scripts/nginx_route.py switch "$CURRENT" || \
        echo "CRITICAL: production recovery could not be verified" >&2

    exit 1
fi


emit_step \
    "success" \
    "Production converged"


END_MS=$(python3 -m opsboard.timing)
DURATION_MS=$((END_MS - START_MS))


if curl \
    --fail \
    --silent \
    --max-time 4 \
    "$OPSBOARD_URL/health" \
    >/dev/null 2>&1
then

    PAYLOAD=$(
        python3 \
            - "$VERSION" \
            "$GIT_SHA" \
            "$IMAGE" \
            "$DURATION_MS" <<'PY'
import json
import sys

version, git_sha, image, duration = sys.argv[1:]

print(
    json.dumps(
        {
            "version": version,
            "git_sha": git_sha,
            "image": image,
            "status": "rolled_back",
            "duration_ms": int(duration),
        }
    )
)
PY
    )

    printf '%s' "$PAYLOAD" | python3 -m opsboard.history || true

else

    echo
    echo "WARNING: OpsBoard API unavailable."
    echo "Rollback history was not recorded."

fi


echo
echo "========================================"
echo " ROLLBACK SUCCESSFUL"
echo "========================================"
echo
echo "Production slot : $TARGET"
echo "Version         : $VERSION"
echo "Git SHA         : $GIT_SHA"
echo "Duration        : ${DURATION_MS} ms"
echo
