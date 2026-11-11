# OpsBoard Kubernetes lab

Argo CD tracks `main:k8s/opsboard` in `Mishkaaass/ci-cd-lab`.
`k8s/argocd/opsboard.yaml` bootstraps its AppProject and Application;
it is applied separately after merging the manifests and adding Git credentials.

## Reviewer setup: isolated, reproducible lab

This repo now includes a **dedicated** kind/Argo CD bootstrap. It uses a
cluster called `opsboard-review` and a private kubeconfig in
`~/.local/state/opsboard-gitops-review/`, **not** your default context or
the owner's older `kind-ci-cd-platform` environment.

Install Docker Engine, kind and kubectl first, then run from the checkout:

```bash
bash scripts/gitops-demo.sh doctor
bash scripts/gitops-demo.sh up
bash scripts/gitops-demo.sh status
bash scripts/gitops-demo.sh drift-test
```

The bootstrap installs pinned Argo CD v3.6.1, generates fresh *local* OpsBoard
and PostgreSQL credentials, and creates the Kubernetes Secrets outside Git.
It uses the manifest's digest-pinned GHCR image; **it does not build or silently
promote a new version.** The `drift-test` changes replicas to 2 in this isolated
cluster, waits for Argo to restore Git's `replicas: 1`, and restores 1 itself
on timeout. This demonstrates self-healing, not a Kubernetes rollback.

**Repository and package visibility:** With a public GitHub repo and public GHCR
package, the bootstrap can read both without credentials. Private resources
require dedicated read-only token files:

```bash
# Example paths; create the files securely yourself. Never paste token values.
GITOPS_READ_TOKEN_FILE="$HOME/.config/opsboard/git-read.token" \
GHCR_TOKEN_FILE="$HOME/.config/opsboard/ghcr-read.token" \
GHCR_USERNAME="your-github-username" \
bash scripts/gitops-demo.sh up
```

Only set the variables needed for private resources. GitHub repository read
access and GHCR `read:packages` are the intended minimum privileges. Tokens
are never passed on the command line or written into Git, but their pull
credentials **are** stored as Kubernetes Secrets in the disposable cluster
and as private configuration in the user's home directory. Use dedicated
low-privilege credentials. Do not use an admin or broad-scoped personal token.

To use your fork instead of the original repository, pass
`GITOPS_REPO_URL=https://github.com/OWNER/FORK.git`. Argo tracks its `main`
branch. The image reference in the manifest may still use the original GHCR
package unless your fork deliberately changes it in a reviewed commit.

The following commands use local-only port forwarding:

```bash
bash scripts/gitops-demo.sh ui   # https://127.0.0.1:18080, Argo CD
bash scripts/gitops-demo.sh app  # http://127.0.0.1:18081, Kubernetes OpsBoard
```

Retrieve Argo's initial admin password from `argocd-initial-admin-secret`
using the **dedicated** kubeconfig/context from the README. OpsBoard viewer
and operator token files are saved under the private state directory. Never
share these tokens/screenshots.

**Cleanup is explicitly destructive:**
`bash scripts/gitops-demo.sh down --delete-my-lab` deletes only the owned
`opsboard-review` cluster, including its disposable PostgreSQL PVC. It refuses
an unknown cluster with the same name. Local secret files are preserved
for inspection; never treat the kind PVC as a backup.

The older manual GitOps runbook below describes the author's original cluster.
The two environments must not be mixed or pointed at the same live database.

## Components

- `opsboard` Deployment and Service: FastAPI on container port 8000, Service port 80.
- `/health`: process liveness; `/ready`: database readiness.
- `postgres` StatefulSet and headless Service: PostgreSQL 18 with a 1 Gi PVC.
- Application and database images are pinned by digest.
- Application tables are initialized by the existing FastAPI lifespan handler.

## Bootstrap prerequisites

Use the dedicated `kind-ci-cd-platform` context and kubeconfig at
`$HOME/.config/ci-cd-platform/kubeconfig`, with Argo CD installed in `argocd`.
Create the `opsboard` namespace and these Secrets locally, outside Git:

- `opsboard/ghcr-pull`: registry credentials, classic PAT with `read:packages`.
- `opsboard/opsboard-db`: generated `POSTGRES_DB`, `POSTGRES_USER`,
  `POSTGRES_PASSWORD` and `DATABASE_URL` pointing to `postgres:5432`.
- An Argo CD repository Secret in `argocd`: a dedicated read-only Git credential
  for `https://github.com/Mishkaaass/ci-cd-lab.git`.
- `opsboard/opsboard-auth-<hash>`: an auth JSON Secret matching the `secretName`
  mounted in `app.yaml` (a versioned name derived from private auth configuration).

Preserve the original database credentials when reusing its PVC.
The local-path PVC survives Pod replacement. It is not a backup and does not
protect against losing or deleting the kind node/cluster.

## Deployment flow

Edit manifests, validate against the cluster, open a PR, wait for CI, and merge.
Once bootstrapped, Argo CD syncs `main` and repairs managed resource drift.
The AppProject permits only Services, Deployments and StatefulSets in `opsboard`.
Automatic pruning is disabled; the Application has no cascading-deletion finalizer.
These settings do not prevent an operator from explicitly deleting cluster data.

CI/CD publishes verified images but **does not automatically change** the
GitOps image digest. To promote a new verified application image, update
`image`, `APP_VERSION` and `GIT_SHA` together in `app.yaml`, then review and
merge that change. A GitOps commit SHA can differ from the application build
SHA: `/version` reports the latter. See [Release checklist](release-checklist.md).
Rollback restores the previous **verified image and matching version metadata**
through a reviewed GitOps PR/revert; never roll back by mutating the running
Deployment directly.

The existing dashboard deployment controls still target the Docker Compose demo;
they do not control this Kubernetes deployment.

Security-hardened releases additionally require an auth Secret and a verified
image promotion; see [security-lab.md](security-lab.md). The existing pinned image
is unchanged until that explicit promotion is reviewed and merged.
