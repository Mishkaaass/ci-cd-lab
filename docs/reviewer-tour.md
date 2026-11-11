# Reviewer tour and troubleshooting

This is a small, bounded, reproducible learning lab. It is NOT a hosted production
service. Do not give the browser shell Docker access and do not expose local ports
to the internet. All UI ports bind to `127.0.0.1`.

## Five-minute local demo

1. `bash scripts/reviewer.sh doctor` — check Python 3.14, Docker and tools.
2. Terminal A: `bash scripts/reviewer.sh dashboard` — local authenticated FastAPI.
3. Terminal B: `bash scripts/reviewer.sh up` — Compose DB, blue, green, Nginx.
4. Open `http://127.0.0.1:18001/dashboard` and unlock using a local viewer token.
5. `bash scripts/reviewer.sh drill` — intentionally broken, then healthy, then rollback.
6. `bash scripts/reviewer.sh status` — check current service identities.

The broken deploy's own exit status is deliberately nonzero. The **whole drill**
returns zero only if traffic stays on the old release, switches to a verified
healthy candidate, and returns to the exact baseline version/SHA.

The CLI invokes Docker with the terminal's sudo authentication; the dashboard
remains unprivileged. Only incidents and operations exposed through authenticated
API routes may be created in the browser. Viewer is read-only.

## Security evidence (no simulated PASS badges)

| Claim | Verify |
| --- | --- |
| PR CI | `.github/workflows/ci.yml` / GitHub Actions: seven named jobs |
| Secrets | Gitleaks action scans Git history; no tokens in source |
| Dependencies | pip-audit + Ruff/Bandit in CI |
| Container/image | Trivy config and OS/library vulnerability policies |
| Runtime attacks | Chromium/API security tests and isolated ZAP scan |
| SBOM/provenance | Buildx `sbom: true`, `provenance: mode=max` in `cd.yml` |
| Immutable deploy | GHCR digest and matching `APP_VERSION`/`GIT_SHA` in GitOps |
| Failure recovery | `bash scripts/reviewer.sh drill` live response identity checks |
| GitOps self-heal | `bash scripts/gitops-demo.sh drift-test` on an owned kind cluster |

An image passing policy can still report **unfixed HIGH CVEs**; the gate blocks
all CRITICAL and **fixable HIGH** findings, per
[container security policy](container-security-policy.md). Avoid claiming
'zero vulnerabilities' or cloud production readiness.

## Common errors

| Error | What to do |
| --- | --- |
| `python3.14 not found` | Install Python 3.14 and `venv`; the app does not silently downgrade. |
| `port ... occupied` | Use `docker ps` and `ss -ltnp` to find its owner; do **not** kill containers blindly. |
| `Compose belongs to another checkout` | Run commands from the checkout that started the existing stack. |
| Dashboard has no service | Start Compose in terminal B, not just the FastAPI UI. |
| `401` | Unlock with the local viewer/operator token file; never share tokens. |
| Browser deploy controls disabled | Expected. Use the terminal drill to avoid remote Docker access. |
| Broken deploy failed | Expected when Nginx is still serving its original release. |
| Argo `Unknown`/`OutOfSync` | Verify Git URL/repo access, repository credentials and Argo controller logs. |
| Kubernetes `ImagePullBackOff` | GHCR package may be private; provide a read-only pull token file. |
| Kubernetes `CrashLoopBackOff` | Inspect Pod logs, database Secret, readiness and PVC. |

The GitOps setup **never edits your global kubeconfig**. Use the dedicated
`--kubeconfig` and `--context` flags shown in the README, especially when
investigating multiple local Kubernetes clusters. The kind PVC lasts only as
long as the kind node survives; it is **not** a backup.
