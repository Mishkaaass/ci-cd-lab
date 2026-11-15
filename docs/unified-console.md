# Unified console — reviewer and security runbook

## Purpose

OpsBoard observes two independent local labs. Docker Blue/Green proves that an unhealthy release never receives traffic and that a healthy promotion can be rolled back to the **exact original version and SHA**. Kubernetes/Argo CD proves Git-defined reconciliation after manually induced replica drift. CI/CD evidence comes from actual GitHub Actions metadata.

## One-command reviewer experience

From the repository root on Linux, run `bash scripts/showcase.sh`, keep that terminal open, and visit `http://127.0.0.1:18002/`. Read the private Viewer token locally with `cat ~/.config/ci-cd-lab/unified-console/viewer.token`, unlock, and open **Live demo**. Select **Run full showcase** or an individual drill. The retained event stream shows the actual **Blue → Green → Blue** switch and the separate **1 → 2 → 1** GitOps recovery. Click **Pipeline & security** to inspect the latest real CI jobs.

The launcher can re-use the existing Docker demo (including a verified `demo1-*` checkout) and connects the port `18001` history API if it is not already active. It will start the demo Compose services when they are offline. Kubernetes remains an independent setup; bootstrap it once using `bash scripts/gitops-demo.sh up` if needed.

`bash scripts/unified-console.sh serve` provides the alternative **read-only** viewer without starting labs or allowing demo requests. Its `doctor` mode reports CLI prerequisites. Ordinary viewers can inspect environment state, but no Docker or Kubernetes command is issued.

## What does a live drill change?

**Docker:** The existing guarded `scripts/reviewer.sh drill` runs against the local Compose lab; it recreates an **inactive** candidate, rejects an unhealthy candidate, validates readiness/identity, switches Nginx traffic to a healthy candidate, then performs an exact rollback. The final state is normally Blue. Repeating the drill is not the same as publishing a new GHCR image or moving the Kubernetes image digest.

**GitOps:** The existing guarded `scripts/gitops-demo.sh drift-test` temporarily scales a Deployment in the **dedicated** kind cluster, then waits for Argo CD to reconcile the desired state from Git. This is **not an image rollback**. The PostgreSQL PVC is preserved, but persistence is not a backup.

**History and CI:** The console polls the live Nginx app, pinned-context `kubectl` reads, the legacy Docker audit API and GitHub Actions. GitHub job names are shown exactly as returned (e.g. `Python tests`, `Code quality`) rather than assuming a `CI/` prefix. If GitHub cannot return the job list, details remain **Unavailable**, never green by assumption.

## Security model

- The viewer listens only on `127.0.0.1`. All API data requires the private `0600` local Viewer token, which is kept in browser tab memory.
- `scripts/showcase.sh` enables an **explicit**, fixed-scope demo session. An authenticated POST can request only `all`, `docker` or `gitops`, and only while the terminal supervisor is alive. The web process queues typed actions through a `0700` private state directory. It never interprets user text as a shell command, opens the Docker socket, changes kubeconfig context, or accepts arbitrary paths.
- The independent terminal supervisor executes only the **existing guarded scripts**. Docker `sudo` authorization, if necessary, occurs in the terminal. Do not enable local actions on a shared workstation. Closing the launcher disables them.
- Requests are loopback-only, require Bearer auth and matching host/origin; cross-origin requests and unrelated HTTP POST endpoints are rejected. HTML uses text nodes for untrusted source values; the CSP disallows remote scripts and framing.
- No action is automatically triggered when the viewer opens. The user must explicitly click Run.
- Event history stores only a fixed allowlist of titles and states; it never stores terminal output containing credentials. No release, PVC, cluster or Compose volume deletion is performed on exit.

## Startup and troubleshooting

`18002` is the unified UI and viewer API. `18001` is the older Docker audit API; the launcher starts it when needed. `8080` is the Nginx live release. To inspect manually, run `bash scripts/reviewer.sh status`, `bash scripts/reviewer.sh dashboard`, `bash scripts/gitops-demo.sh status`, and `gh auth status`. For Argo's separate native UI use `bash scripts/gitops-demo.sh ui` (port `18080`). For Kubernetes's older OpsBoard use `bash scripts/gitops-demo.sh app` (port `18081`) and its distinct token.

If port `18002` is already in use, stop the existing console using `Ctrl+C` in its terminal before rerunning the launcher. Do not stop unknown PIDs or delete Docker volumes. If Docker needs `sudo` after the local timestamp expires, type the password in the launcher's terminal; it is never accepted by the browser. CI without authenticated GitHub CLI access will show unavailable job details.

## Release and promotion boundaries

GitHub Actions CI has seven required jobs. On a successful push to protected `main`, CD can build, scan, verify image digest, generate SBOM/provenance, publish to GHCR and update the mutable `latest` tag. Kubernetes receives a new app image **only after a separate reviewed manifest change**, pinned by immutable digest. Neither read-only observation nor the guided drills rewrite release tags or edit GitOps manifests.

Stop the launcher with `Ctrl+C` to stop only the servers started by that launcher. Cluster and PVC remain. `bash scripts/gitops-demo.sh down --delete-my-lab` is destructive; do not run it for ordinary shutdown.
