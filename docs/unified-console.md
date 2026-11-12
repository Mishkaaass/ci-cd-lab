# Unified OpsBoard · operational notes

**Purpose:** One read-only local control center observing two existing, isolated delivery labs. The console does not replace Argo CD, Docker Compose, deployment scripts or their credential boundaries.

## Start

From the repository root, after starting the labs you want to inspect:

```bash
bash scripts/unified-console.sh doctor
bash scripts/unified-console.sh
```

Open `http://127.0.0.1:18002`. The token is created once as `~/.config/ci-cd-lab/unified-console/viewer.token` with mode `0600`. Read it on your own machine using `cat` and paste into the unlock form. Do not put tokens in shell history, screenshots, source control or CI artifacts. The browser stores it **in memory only** until the tab reloads or you lock it.

## Data sources

| Section | Read-only source | If not available |
|---|---|---|
| Docker release | Loopback `:8080/version`, `:8080/ready`, `:8001/version`, `:8002/version` | Unavailable; never assumed healthy |
| Docker audit | Legacy OpsBoard `:18001/api/deployments` using the local legacy Viewer token when found | History unavailable; Docker live state still works |
| GitOps | `kubectl` with **explicit** `kind-opsboard-review` context and dedicated kubeconfig; reads `application/opsboard`, `deployment/opsboard`, `pvc/data-postgres-0` | Cluster unavailable |
| CI | Authenticated local `gh api` read-only calls for the latest `main` CI run and its jobs | CI unavailable; no invented pass |

Local `gh` credentials are managed by GitHub CLI; the console never displays them. No shell expansion from HTTP requests is possible; commands are fixed and use timeouts. The console listens **only** on `127.0.0.1`, rejects unexpected Host/Origin, enforces Content Security Policy, and has **no mutating HTTP endpoints**. `POST` is rejected. There are no analytics beacons or external assets.

## Operations

The **Runbooks** section provides copyable commands for the guarded Docker release drill and the GitOps drift test. Run them from the repository root after reviewing the environment. Browser-side deploy/rollback buttons are deliberately absent: root-equivalent Docker privileges and cluster writes must not be granted to a read-only monitoring page.

- A Docker drill changes the inactive container, can switch traffic, and rolls back after successful verification.
- A Kubernetes drift test intentionally scales the local demo app and waits for Argo CD to restore the declared state.
- Neither action runs automatically on page refresh.
- This project does not equate a `Bound` PVC with a verified database backup.

## Troubleshooting

- **Docker offline**: `bash scripts/reviewer.sh status` and `curl -f http://127.0.0.1:8080/version`.
- **Kubernetes offline**: `bash scripts/gitops-demo.sh status`. Verify `kind`, `kubectl` and the dedicated kubeconfig; the console does not change your global kube context.
- **No CI results**: run `gh auth status` and `gh api user --jq .login` in your terminal. Stale `GH_TOKEN` and `GITHUB_TOKEN` values may override saved login.
- **History unavailable**: run `bash scripts/reviewer.sh dashboard` in a separate terminal; the source API must be running, and its local Viewer token must match that instance.
- **Viewer login fails**: verify the private `viewer.token` file mode is `0600`, and run the console under the same local user. Reloading the page deliberately forgets the token.
- **Port 18002 occupied**: check the owning process first. Do not kill unrelated services. To use another port run `python3 -m unified_console.server --port 18012` from the repository root.

## Limits

This is a **local portfolio engineering lab** and a deliberately restricted operational viewer. It does not provide OIDC, public TLS termination, writable Kubernetes APIs, hosted multi-tenancy, backups or off-host observability. Version tags/releases are not rewritten; any change merged to `main` can trigger the existing CD workflow and produce a new immutable image.
