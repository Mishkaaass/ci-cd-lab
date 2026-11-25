# Unified console — reviewer and security runbook

## Purpose

OpsBoard observes two independent local labs. Docker Blue/Green proves that an unhealthy release never receives traffic and that a healthy promotion can be rolled back to the **exact original version and SHA**. Kubernetes/Argo CD proves Git-defined reconciliation after manually induced replica drift. CI/CD evidence comes from actual GitHub Actions metadata.

## One-command reviewer experience

From the repository root on Linux, run `make requirements` (read-only), `make setup` (creates/reuses project `.venv` with Python 3.14), then `make showcase` (also available as `bash scripts/showcase.sh`). Keep the launch terminal open and visit `http://127.0.0.1:18002/`. **The Unified Console itself needs only Python's standard library; the legacy Docker history API may install pinned `requirements-dev.txt` inside `.venv` on first use, and Docker images install their own Python packages in containers.** See [RUN REQUIREMENTS](REQUIREMENTS.md). Read the private Viewer token locally with `cat ~/.config/ci-cd-lab/unified-console/viewer.token`, unlock, and open **Live demo**. Select **Run full showcase** or an individual drill. Read the separate private operator token using `cat ~/.config/ci-cd-lab/unified-console/operator.token`, enter it in the password dialog, and approve with `RUN all`, `RUN docker`, or `RUN gitops` in the launcher terminal. Without that exact approval no drill runs. The retained event stream shows the actual **Blue → Green → Blue** switch and the separate **1 → 2 → 1** GitOps recovery. Click **Pipeline & security** to inspect the latest real CI jobs.

The launcher can re-use the existing Docker demo (including a verified `demo1-*` checkout) and connects the port `18001` history API if it is not already active. It will start the demo Compose services when they are offline. Kubernetes remains an independent setup; bootstrap it once using `bash scripts/gitops-demo.sh up` if needed.

`make viewer` (equivalent to `bash scripts/unified-console.sh serve`) provides the alternative **read-only** viewer under `.venv/bin/python` without starting labs, installing third-party packages or allowing demo requests. Its `doctor` mode reports CLI prerequisites. Ordinary viewers can inspect environment state, but no Docker or Kubernetes command is issued.

## What does a live drill change?

**Docker:** The existing guarded `scripts/reviewer.sh drill` runs against the local Compose lab; it recreates an **inactive** candidate, rejects an unhealthy candidate, validates readiness/identity, switches Nginx traffic to a healthy candidate, then performs an exact rollback. The final state is normally Blue. Repeating the drill is not the same as publishing a new GHCR image or moving the Kubernetes image digest.

**GitOps:** The existing guarded `scripts/gitops-demo.sh drift-test` temporarily scales a Deployment in the **dedicated** kind cluster, then waits for Argo CD to reconcile the desired state from Git. This is **not an image rollback**. The PostgreSQL PVC is preserved, but persistence is not a backup.

**History and CI:** The console polls the live Nginx app, pinned-context `kubectl` reads, the legacy Docker audit API and GitHub Actions. GitHub job names are shown exactly as returned (e.g. `Python tests`, `Code quality`) rather than assuming a `CI/` prefix. If GitHub cannot return the job list, details remain **Unavailable**, never green by assumption.

## Security model

- The viewer listens only on `127.0.0.1`. All API data requires the private `0600` local Viewer token, which is kept in browser tab memory.
- `scripts/showcase.sh` enables an **explicit**, fixed-scope demo session. A POST authenticated with both the Viewer token and a separate private Operator token can request only `all`, `docker` or `gitops`, and only while the terminal supervisor is alive. The web process queues typed actions through a `0700` private state directory. It never interprets user text as a shell command, opens the Docker socket, changes kubeconfig context, or accepts arbitrary paths.
- The independent terminal supervisor executes only the **existing guarded scripts**. Docker `sudo` authorization, if necessary, occurs in the terminal. Do not enable local actions on a shared workstation. Closing the launcher disables them.
- Requests are loopback-only, require Bearer auth and matching host/origin; cross-origin requests and unrelated HTTP POST endpoints are rejected. HTML uses text nodes for untrusted source values; the CSP disallows remote scripts and framing.
- No action is automatically triggered when the viewer opens. The user must explicitly click Run, enter the separate Operator credential and confirm the exact drill in the foreground terminal. Viewer credentials alone cannot queue operations. The two credentials are not interchangeable.
- Event history stores only a fixed allowlist of titles and states; it never stores terminal output containing credentials. No release, PVC, cluster or Compose volume deletion is performed on exit.

## Startup and troubleshooting

`18002` is the unified UI and viewer API. `18001` is the older Docker audit API; the launcher starts it when needed. `8080` is the Nginx live release. To inspect manually, run `bash scripts/reviewer.sh status`, `bash scripts/reviewer.sh dashboard`, `bash scripts/gitops-demo.sh status`, and `gh auth status`. For Argo's separate native UI use `bash scripts/gitops-demo.sh ui` (port `18080`). For Kubernetes's older OpsBoard use `bash scripts/gitops-demo.sh app` (port `18081`) and its distinct token.

If port `18002` is already in use, stop the existing console using `Ctrl+C` in its terminal before rerunning the launcher. Do not stop unknown PIDs or delete Docker volumes. If Docker needs `sudo` after the local timestamp expires, type the password in the launcher's terminal; it is never accepted by the browser. CI without authenticated GitHub CLI access will show unavailable job details.

## Release and promotion boundaries

GitHub Actions CI has seven required jobs. On a successful push to protected `main`, CD can build, scan, verify image digest, generate SBOM/provenance, publish to GHCR and update the mutable `latest` tag. Kubernetes receives a new app image **only after a separate reviewed manifest change**, pinned by immutable digest. Neither read-only observation nor the guided drills rewrite release tags or edit GitOps manifests.

Stop the launcher with `Ctrl+C` to stop only the servers started by that launcher. Cluster and PVC remain. `bash scripts/gitops-demo.sh down --delete-my-lab` is destructive; do not run it for ordinary shutdown.

## Live terminal, sudo and reviewability

The **Live terminal** displays a small, read-only set of lines matched against explicit allowlisted output from the guarded scripts. It is **not** a shell, PTY or Docker console. Arbitrary stdout, tokens, passwords and sensitive paths are never forwarded to the browser. The interface polls a bounded, private JSON snapshot once a second.

The web UI starts **before** Docker/kind preparation. If Docker needs interactive sudo, the UI enters `waiting_auth` and shows a clear amber banner. Enter the password only in the terminal running `bash scripts/showcase.sh`; nothing is entered over HTTP. A denied or timed-out prompt is reported as a failure.

`Ctrl+C` stops the launcher and servers, while Compose volumes, kind resources and the PostgreSQL PVC are preserved.

App header credit: **Developed by Moshe Bogo**.
