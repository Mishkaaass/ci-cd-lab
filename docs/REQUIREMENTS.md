# Run requirements — OpsBoard reviewer

This repository has **two independent hands-on labs** and one browser console. Pick your starting path. **Only the `make showcase` path prepares live containers and a dedicated Kubernetes cluster.**

| Path | Required on the host | Command | Side effects |
|---|---|---|---|
| **Read-only Unified Console** | Linux, Python **3.14** with `venv`, Bash/Make, browser | `make requirements` → `make setup` → `make viewer` | Creates `.venv/` and a private viewer token; **no Docker builds/deployments** |
| **Docker Blue/Green only** | Above + Git, curl, Docker Engine and Compose v2, terminal access to Docker (possibly `sudo`) | `bash scripts/reviewer.sh doctor` → `bash scripts/reviewer.sh dashboard` (Terminal A), `bash scripts/reviewer.sh up` (Terminal B), `bash scripts/reviewer.sh drill` | Creates local Compose containers/volumes; deliberately changes **demo** traffic |
| **Full Guided Showcase** | Above + `kind`, `kubectl`, internet and enough RAM/disk for local Kubernetes/Argo CD | `make showcase` (or `bash scripts/showcase.sh`) | Starts/repairs local Docker services, may create dedicated kind cluster, and runs fixed drills **after explicit UI action** |
| **Windows (Ubuntu WSL 2)** | WSL 2 Ubuntu + Docker Desktop with Linux containers/WSL integration + browser | PowerShell: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-showcase.ps1` | May request approval for Ubuntu packages; uses WSL-scoped Python, Docker and own kind cluster |
| **Contributing / Python tests** | Python **3.14** + `venv`, internet for PyPI | `make setup-dev` then `.venv/bin/python -m pytest` | Installs pinned `requirements-dev.txt` **only into `.venv`**, not system Python |

**New user?** Begin with the **read-only console**. You can learn the architecture and inspect the latest available CI/CD results without building containers. The full showcase is separate and has real, local effects. No AWS account is involved.

## Recommended isolated Python setup

```bash
git clone https://github.com/Mishkaaass/ci-cd-lab.git
cd ci-cd-lab
make requirements       # read-only inventory, shows optional tools separately
make setup              # create/reuse .venv with Python 3.14; no pip installs
make viewer             # read-only console at http://127.0.0.1:18002/
```

The viewer and local showcase supervisor use only the **Python standard library**. `make setup` **does not install `requirements.txt`**, because the viewer does not import FastAPI or SQLAlchemy. It reuses an existing compatible `.venv` and refuses to overwrite an incomplete or incompatible one. No `source .venv/bin/activate` is needed — launchers explicitly run `.venv/bin/python`.

When ready for both local deployment drills, stop the viewer with `Ctrl+C`, confirm Docker/kind requirements and run:

```bash
make showcase
```

Open `http://127.0.0.1:18002/`, read `~/.config/ci-cd-lab/unified-console/viewer.token` **locally** and unlock. The Viewer token is private; do not share it. The full showcase may request a **Linux sudo password in the foreground terminal** to access Docker, never in the browser. Click the explicit **Live Demo** action to run Docker/GitOps drills. Stop the launcher with `Ctrl+C`; Compose volumes and Kubernetes PVC are preserved.

> **Don't launch `make viewer` and `make showcase` together:** both use port `18002`. If a port is occupied, stop your own earlier instance. Never kill unknown processes or delete Docker volumes to free a port.

## What `requirements*.txt` actually installs

| File | Used for | Where installed |
|---|---|---|
| `requirements.txt` | FastAPI/SQLAlchemy/PostgreSQL, legacy OpsBoard web API | Inside the primary Docker image, and via `requirements-dev.txt` for local dashboard development |
| `requirements-demo.txt` | Blue and Green FastAPI demo service | **Inside Docker demo images** |
| `requirements-dev.txt` | `requirements.txt` + pytest, Ruff, Bandit, pip-audit | Into project **`.venv`** only when `make setup-dev` is explicitly used; the legacy dashboard launcher may also install it into `.venv` on first use |
| `requirements-browser.txt` | Dev requirements + Playwright browser tests | For optional local browser-security testing (separate from viewer) |

**A Python venv does not install Docker, kubectl, kind, GitHub CLI, Nginx or PostgreSQL.** These are **external tools/services**. Docker installs application Python dependencies **inside its containers**, not into the host `.venv`. Kubernetes workloads are separate containers, not processes inside the host virtual environment.

There is no need to run `pip install -r requirements.txt` just to view the console. **Never use `sudo pip`, `pip install --break-system-packages`, or globally replace system Python.** An existing incompatible `.venv` is preserved and reported rather than silently deleted.

## Local ports, safety and verification

| Port | Service | Required when |
|---|---|---|
| `18002` | Unified Console / Viewer token | Viewer or showcase |
| `18001` | Legacy OpsBoard API and history | Docker legacy dashboard / full showcase |
| `8080` | Nginx live Blue/Green proxy | Docker demo |
| `8001`, `8002` | Blue and Green candidate services | Docker demo |
| `5432` | Local PostgreSQL container | Docker demo |
| `18080`, `18081` | Argo CD and Kubernetes OpsBoard port-forwards | Optional GitOps UIs |

On a new checkout, `make requirements` is deliberately **read-only** and reports what is missing before running. Docker permissions are deliberately **not modified**; do not `chmod 666 /var/run/docker.sock` or blindly add the user to the docker group (root-equivalent capability). A running viewer is not proof that Docker or Kubernetes is ready. Readiness must come from actual `scripts/reviewer.sh status` and `scripts/gitops-demo.sh status` responses.

`make showcase` may use the same local `.venv` for the legacy FastAPI API, which installs pinned developer packages if needed; that portion **can download packages**. The standalone **viewer mode** never installs them. The first full run can take significantly longer than five minutes.

The GitOps lab **does not mutate your default kubeconfig**, and the kind PVC is **not a backup**. Destroying the dedicated cluster using `bash scripts/gitops-demo.sh down --delete-my-lab` loses its PVC; this is **never** part of normal shutdown.

## If something fails

- **Python 3.14 / `venv` missing:** install Python 3.14 for your user, with venv support, and rerun `make requirements`; no global `pip` changes.
- **`.venv` incompatible or incomplete:** stop and inspect the directory. Setup intentionally refuses to delete it.
- **Docker permission denied:** enable trusted Docker Engine/WSL integration, or run the normal terminal supervisor with your existing authorized `sudo` flow. Never change socket permissions for convenience.
- **`18002` already in use:** stop your prior viewer/showcase with `Ctrl+C` in that terminal.
- **No `kind` or `kubectl`:** you can still use the viewer and Docker Blue/Green demo. GitOps requires both.
- **GitHub CI/CD details unavailable:** `gh` is optional. Authenticate only for reading your own details; the UI correctly reports `Unavailable` when it cannot fetch evidence.

For the detailed demos, see [Docker Blue/Green](demo-docker-blue-green.md), [Kubernetes/Argo CD](demo-kubernetes-argocd.md), [Windows/WSL](windows.md) and the [Security Model](security-lab.md).
