# OpsBoard Kubernetes lab

Argo CD tracks `main:k8s/opsboard` in `Mishkaaass/ci-cd-lab`.
`k8s/argocd/opsboard.yaml` bootstraps its AppProject and Application;
it is applied separately after merging the manifests and adding Git credentials.

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

Preserve the original database credentials when reusing its PVC.
The local-path PVC survives Pod replacement. It is not a backup and does not
protect against losing or deleting the kind node/cluster.

## Deployment flow

Edit manifests, validate against the cluster, open a PR, wait for CI, and merge.
Once bootstrapped, Argo CD syncs `main` and repairs managed resource drift.
The AppProject permits only Services, Deployments and StatefulSets in `opsboard`.
Automatic pruning is disabled; the Application has no cascading-deletion finalizer.
These settings do not prevent an operator from explicitly deleting cluster data.

CI/CD publishes verified images but does not yet change the GitOps image digest.
To promote a new verified application image, update `image`, `APP_VERSION` and
`GIT_SHA` together in `app.yaml`, then review and merge that change.
Rollback uses a reviewed Git revert of the relevant deployment change.

The existing dashboard deployment controls still target the Docker Compose demo;
they do not control this Kubernetes deployment.
