# Linux — OpsBoard setup

Ubuntu/Debian with a non-root user is the reference route. Other Linux distributions may work with equivalent tools. Use a dedicated lab, never a production Docker daemon or Kubernetes cluster.

## Install prerequisites

- Git, Bash, Make, curl, GNU coreutils (sha256sum), util-linux (flock), and sudo if your Docker setup requires it.
- Python **3.14** with venv. Install from your distribution when available or a trusted user-scoped tool such as [uv](https://docs.astral.sh/uv/guides/install-python/); do not replace system Python.
- Only for live drills: [Docker Engine + Compose v2](https://docs.docker.com/engine/install/), [kind](https://kind.sigs.k8s.io/docs/user/quick-start/) and [kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/). Verify downloaded binaries against official checksums.
- Optional: [GitHub CLI](https://cli.github.com/) for live CI/CD metadata. Keep credentials private.

On Ubuntu/Debian, after reviewing the package-manager changes, install missing basic utilities if needed:

```bash
sudo apt update
sudo apt install git make curl coreutils util-linux
```

Install Python separately as above if needed. A user-scoped uv installation can provide it using `uv python install 3.14`; ensure the installed `python3.14` is on PATH.

## Clone and inspect first

```bash
git clone https://github.com/Mishkaaass/ci-cd-lab.git
cd ci-cd-lab
make requirements
make setup
make viewer
```

Open http://127.0.0.1:18002/ and read the private token from another terminal:

```bash
cat "${XDG_CONFIG_HOME:-$HOME/.config}/ci-cd-lab/unified-console/viewer.token"
```

Viewer mode needs no Docker or cluster. Stop with Ctrl+C.

## Run the full local demonstration

After installing the optional tools, check `docker info`, `docker compose version`, `kind version` and `kubectl version --client`. If Docker requires sudo, use the documented terminal authorization; never loosen socket permissions.

Stop the viewer, then in the same checkout:

```bash
make showcase
```

Unlock the browser with the Viewer token. For a live drill use the separate `operator.token` in the same private directory; enter `RUN all` (or `RUN docker` / `RUN gitops`) in the original terminal to authorize the action. Do not publish either token.

See the [full reviewer demo](../README.md), [run requirements](REQUIREMENTS.md), [Docker runbook](demo-docker-blue-green.md) and [GitOps runbook](demo-kubernetes-argocd.md). Ctrl+C preserves containers, volumes and the lab's PVC. No AWS account is needed.
