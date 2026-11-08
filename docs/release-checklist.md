# Release and final verification checklist

This is a **manual GitOps promotion** playbook for the OpsBoard learning lab.
It is separate from the automatically triggered GitHub Actions CD workflow.
All checks must use a known commit and verified GHCR image digest; never choose
an image solely because its `latest` tag exists.

## 1. Verify the upstream release

- PR CI and `main` CI succeeded, including all security gates.
- CD succeeded for a successful **push** CI run on `main`.
- The CD log contains exactly one `OPSBOARD_VERIFIED_RELEASE={...}` record.
- Save both the `git_sha` and the immutable `image` digest from that record.
- Confirm the CD security steps and isolated authenticated ZAP smoke tests passed.
- The record is the application build's identity, not the GitOps manifest commit.

## 2. Promote with a narrow pull request

From a clean branch based on the current `main`, change **only** these fields
in `k8s/opsboard/app.yaml`:

```yaml
image: ghcr.io/mishkaaass/ci-cd-lab@sha256:<verified-image-digest>
# Within the application's container env list:
- name: APP_VERSION
  value: sha-<first-seven-characters-of-verified-app-sha>
- name: GIT_SHA
  value: <full-40-character-verified-app-sha>
```

The excerpt above shows the three target fields; it is **not** an entire
Kubernetes resource and should not replace the original manifest. Preserve
`opsboard-auth-*`, `opsboard-db`, `ghcr-pull`, resource limits and PVC settings.
Run `git diff --check`, inspect the one-file diff, open a PR, wait for seven CI
jobs to pass, then merge following normal review. `scripts/prepare-security-promotion.py`
only supports first-time auth wiring; it deliberately refuses already-wired
manifests and is not the tool for repeated promotions.

## 3. Verify running state (read-only)

Use only the dedicated kind context, never an arbitrary Kubernetes context:

```bash
export KUBECONFIG="$HOME/.config/ci-cd-platform/kubeconfig"
K="$HOME/.local/share/ci-cd-platform/tools/kind-0.33.0-k8s-1.36.4/kubectl"
test "$("$K" config current-context)" = kind-ci-cd-platform
"$K" -n argocd get application opsboard
"$K" -n opsboard get deployment opsboard -o wide
"$K" -n opsboard get pods -o wide
"$K" -n opsboard get pvc data-postgres-0
```

Confirm Argo CD `Synced/Healthy`, desired=ready=updated replicas, and the
**actual Pod image ID** matches the verified immutable digest. Check `/health`,
`/ready` and `/version` (200, 200 and the expected application SHA).
An unchanged PVC UID and readiness do not prove record-level database survival.

## 4. Rollback and recovery

- Revert the *application release fields together* to a previously verified
  digest and matching SHA in a reviewed PR. Argo CD reconciles after merge.
- Verify Pod digest, service readiness, `/version`, and PVC UID after rollout.
- Preserve Secrets and the StatefulSet/PVC. Do not delete/recreate persistent
  volumes to perform an application rollback.
- For actual backup/restore claims, use a separate tested database backup,
  restore, and known-record validation. A kind local-path volume is not a backup.
- The Compose `scripts/rollback.sh` is **not** a Kubernetes rollback tool.

## 5. Project completion criteria

- [ ] README explains demo vs Kubernetes runtime truthfully.
- [ ] CI 7/7 and CD successful at the recorded application release SHA.
- [ ] GitOps manifest pins the intended digest and matching release metadata.
- [ ] Argo CD Synced/Healthy and actual Pod digest verified.
- [ ] `/health`, `/ready`, `/version` and authenticated read/write APIs checked.
- [ ] PostgreSQL credentials reviewed and rotated if previously exposed.
- [ ] Known-record persistence and backup/restore evidence captured separately.
- [ ] GitHub repository has no committed private tokens or credentials.

**Never publish real auth tokens, PostgreSQL URLs, kubeconfigs, or Secrets in
issue comments, CI logs, README screenshots, or audit reports.**
