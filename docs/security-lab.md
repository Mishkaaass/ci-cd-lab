# OpsBoard security lab

מטרת השינוי: שתוכל להסביר איזו בקשה נכנסת, איפה היא נבדקת,
מה נחסם, ואיזו בדיקה מוכיחה זאת. אין כאן הבטחה לכיסוי כל התקפה.

## Threats and evidence

| Threat | Control | Evidence |
| --- | --- | --- |
| Unauthorized API access | Expiring bearer tokens; hashed configuration; fail closed | Missing, malformed, expired and revoked credential tests |
| Unauthorized writes/execution | Viewer GET only; operator mutations; deployment backend disabled by default | Denials before DB/monitor/dispatcher calls |
| SQL injection | Existing SQLAlchemy bound parameters retained | SQL payloads remain literal data; original records unchanged |
| Stored XSS | `textContent`, escaped templates and restrictive CSP | Real Chromium checks malicious strings do not create script/image elements |
| Token/data persistence | Token only in JS memory; locked shell; no-store | Browser reload, lock, expiry/offline and delayed-response checks |
| Command/argument injection | Fixed commands, `shell=False`, action/slot allowlists; bounded release identifiers starting with a letter/digit | Malicious options, paths, shell characters and oversized arguments rejected |
| Oversized/slow requests | 16 KiB body, absolute 10 s read deadline, header/target bounds | Chunked, framing, deadline and length tests |
| Resource abuse | Per-process actor/write quotas; bounded limiter keys; paginated queries | 429/Retry-After and pagination tests |
| Credential leakage in logs | Structured audit omits tokens, body and query; container access log disabled | Audit redaction assertions; Docker runtime configuration |
| Vulnerable dependencies/configuration | pip-audit, Bandit, Trivy, Gitleaks and Dependabot | CI jobs; existing container risk policy retained |
| Active API attacks | Authenticated ZAP scan against disposable containers | CI/CD integration; MEDIUM/HIGH findings and incomplete coverage fail |

ZAP's API scan is tuned to APIs and does not substitute for browser XSS tests.
Its operation/execution routes are excluded; targeted authorization and injection
regressions cover those routes without running deployments. ZAP is not a proof
that every endpoint, payload or vulnerability class was exercised.

## Start a local learning instance

Use Python 3.14 and install `requirements-dev.txt` in an isolated virtualenv.
Keep the existing PostgreSQL environment unless you deliberately choose another DB.
The following creates only new private credential files and a new SQLite lab DB:

```bash
(
set -euo pipefail
cd "$HOME/projects/ci-cd-lab-security-hardening"
mkdir -p "$HOME/.config/ci-cd-platform"
security_dir=$(mktemp -d "$HOME/.config/ci-cd-platform/security-lab.XXXXXX")
python3 scripts/create-security-credentials.py "$security_dir/credentials"
export OPSBOARD_AUTH_FILE="$security_dir/credentials/auth.json"
export DATABASE_URL="sqlite:///$security_dir/lab.db"
export OPSBOARD_ALLOWED_HOSTS="localhost,127.0.0.1"
export OPSBOARD_ENABLE_DEPLOYMENTS=false
printf 'Read the viewer/operator token locally in: %s\n' "$security_dir/credentials"
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 18001 \
  --no-access-log --no-server-header --no-proxy-headers
)
```

Open `http://127.0.0.1:18001/dashboard`. Read `viewer.token` locally and paste it
into the dashboard. It permits viewing; the operator permits API writes. Both
leave Compose execution disabled in this instance. Keys expire after 30 days
(default; generator permits 1–90 days). Refresh, Lock, or expiry clears access.
Create individual named credentials rather than sharing keys in a real team.

In another terminal, `curl -i http://127.0.0.1:18001/api/incidents` should return
`401`: the request reached the server but lacked authentication. `/health` is
public and returns `200`. `/ready` checks the auth configuration and database.
`403` means authenticated but insufficient role; `422` invalid input; `429` quota.
`503` can mean a missing auth configuration or disabled deployment execution;
read the JSON detail.

Root, health, readiness, version, API documentation/schema and the locked dashboard
shell are intentionally public. All `/api` routes require a bearer header.
Authentication does not accept cookies or query strings. Swagger authorization
is not persisted; its UI assets come from the configured CDN. Use HTTPS before
remote access. These examples deliberately bind only to loopback.

The generator uses a new directory and refuses existing destinations. The server
reads hashes from `OPSBOARD_AUTH_FILE`; plaintext token files stay outside Git.
The file format is a JSON list of `name`, `role`, `token_sha256`, `expires_at`
(Unix UTC seconds). Replace/revoke credentials through controlled local file or
Secret management. Hash matching and expiry are checked on each protected request.

## Tests and pipeline

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m bandit -r app.py opsboard demo_service scripts -ll -ii
.venv/bin/python -m pip_audit -r requirements.txt
```

For browser checks, install `requirements-browser.txt`, run
`.venv/bin/python -m playwright install --with-deps chromium`, then run
`RUN_BROWSER_SECURITY=1 .venv/bin/python -m pytest tests/security/test_browser.py -v`.
Without opt-in those browser tests are explicitly skipped. With opt-in, missing
browser dependencies fail. The browser server uses its own temporary SQLite DB.

CI additionally executes API security tests against PostgreSQL 18 in a fresh
`opsboard_security_test` database. `SECURITY_DATABASE_URL` is accepted only for
that dedicated PostgreSQL database name. Each test creates a unique schema and
removes only that newly created schema. Never point tests at a live database.
The original runner-process-group test uses Python OS APIs instead of `ps`;
its process group/session assertions remain in place.

CI contains the existing quality/tests/dependency/secrets/container gates plus API/
browser security and isolated ZAP. Actions use resolved commit SHAs. Dependabot
proposes pip and Action updates; updates still require review and CI.
Bandit blocks MEDIUM/HIGH confidence MEDIUM/HIGH findings. Trivy configuration
scanning covers Kubernetes; existing image scanning covers OS/language packages.
The documented image policy still allows reported unfixed HIGH vulnerabilities.

`python3 scripts/test-release-security.py IMAGE EXPECTED_GIT_SHA` requires Docker.
Use a newly built test image or the release's immutable digest. It creates a fresh
internal Docker network, a tmpfs PostgreSQL database, a read-only app container
and ZAP. It publishes no ports, mounts no Docker socket into any container, and
uses no deployment backend or user credentials. Only its newly created container
and network IDs are cleaned up. It never targets a supplied server URL.

The scanner profile raises finite quotas only in that disposable app. It verifies
its own authenticated GET/POST history and active-scan completion. Auth failures,
429s, incomplete/oversized history, scanner errors and timeout fail the gate.
Scan/rule duration limits are disabled inside ZAP; the outer 15-minute deadline
fails the entire scan rather than treating partial results as success. Rule10202
(anti-CSRF token) is explicitly excluded for this bearer-only API: mutations have
no ambient cookie authentication. No broad vulnerability ignore list is added.
Sanitized JSON reports omit the generated credentials and are uploaded for7 days.

CD runs only after successful same-repository push CI on main. It retains digest,
SBOM/provenance and image scanning, then tests the published digest with the same
isolated security runner. `latest` is promoted only after all gates pass. Its log
records one `OPSBOARD_VERIFIED_RELEASE` JSON object containing the tested upstream
Git SHA and image digest. This avoids confusing the downstream workflow revision
with the commit actually built.

## Compose compatibility

Deployment actions still target the existing local Compose blue/green demo, not
Kubernetes. To deliberately enable them in that environment, configure both
`OPSBOARD_ENABLE_DEPLOYMENTS=true` and `OPSBOARD_RECORD_TOKEN_FILE` pointing to an
operator token file, along with `OPSBOARD_AUTH_FILE`. The shell callbacks now use
`python3 -m opsboard.history`, which reads its token from a file and sends only an
Authorization header. It refuses redirects and unsafe destination URL formats.
History failure warns and does not change the traffic-switch result. Keep this
privileged backend restricted to trusted operators; its Docker/sudo access remains
powerful. Command output capture is not a general log-volume defense.

## Kubernetes activation is a separate promotion

The existing Kubernetes manifest deliberately continues to pin the old verified
image. This source patch alone does not secure that running deployment. Do not
mount new auth configuration into an old release and assume it enforces access.
First merge/release this change and obtain a successful security-enabled CD run.

From a clean branch containing this code, preview:

```bash
python3 scripts/prepare-security-promotion.py \
  --run ACTUAL_SUCCESSFUL_CD_RUN_ID \
  --auth-file /absolute/private/path/auth.json
```

It verifies the CD result and canonical release record, validates unexpired auth
configuration, and previews digest, version/SHA and auth Secret wiring together.
Only `--apply` writes the manifest. It never changes cluster resources. Its output
names a versioned Secret derived from the auth file hash. Create that new Secret
in `opsboard` outside Git before deploying the reviewed promotion; do not replace
existing DB/registry credentials. Mark it immutable and mount the exact auth.json.
Then validate the manifests, review the Git diff and merge. Let Argo sync only
once its read-only repository credential and Application are bootstrapped.
The existing PostgreSQL PVC and credentials require no migration for this change.

## Limits and remaining work

This is a bounded internal-tool security lab, not a completed production platform.
Transport TLS/Ingress, OIDC/MFA, per-person identity lifecycle, a non-superuser DB
runtime role, enforced network isolation, backup/restore drills, image-signature
admission and monitoring/alerting need separate implementation and verification.
The per-process quota is not distributed or network DDoS protection. Kind PVCs
survive Pod replacement, not losing the cluster. Existing DB roles were not changed.
Local browser/SQLite evidence does not establish PostgreSQL, Docker, ZAP or actual
GitHub workflow success; check those jobs before merging or promoting a release.

References: [ZAP API scan](https://www.zaproxy.org/docs/docker/api-scan/),
[ZAP auth headers](https://www.zaproxy.org/docs/desktop/start/features/authentication/),
[OWASP ASVS](https://asvs.owasp.org/),
[SQLAlchemy bound parameters](https://docs.sqlalchemy.org/en/20/tutorial/dbapi_transactions.html).
