# Engineering Learning Lab — Understand the System

This is a guided, **educational**, client-side feature inside the existing OpsBoard console. It teaches *why each mechanism works*, not just how to click **Run full showcase**.

## Start

Launch the normal local showcase from the repository root:

```bash
bash scripts/showcase.sh
```

Open http://127.0.0.1:18002/ and unlock the viewer console with the Viewer token **from your own local file**. Select **Engineering lab** in the sidebar. You can also explore in viewer-only mode via `bash scripts/unified-console.sh serve`. The exercises require no additional privileges and do not change your infrastructure.

## Six interactive modules / 18 practical scenarios

| Module | What you predict | What to inspect |
|---|---|---|
| Docker & Nginx | Rejection of failed readiness; how Nginx switches; independent identity proof | Live Blue/Green slot, `:8080/version`, existing guarded Docker drill |
| Kubernetes & Argo CD | Replica drift (1→2→1); PVC vs application readiness; image-promotion boundary | Argo sync/health, ready/desired replicas, immutable image, PVC |
| Python & FastAPI | Health vs readiness, `SELECT 1`, restricted terminal actions | `app.py` endpoint source and local `:18001/ready` |
| PostgreSQL & persistence | Containers vs named volumes; PVC vs backups; deployment records | `compose.yml`, authenticated FastAPI history routes |
| CI/CD & artifacts | Matching full source commits; GHCR versus deployed digest; incomplete job evidence | GitHub CI/CD run results, recorded Kubernetes image |
| Security & failure design | Credential boundaries, safe read-only lab exercises, honest unavailable status | `unified_console/server.py`, CI job evidence |

Every question is multiple choice. A **correct answer** marks that question completed for the current browser tab. An incorrect answer explains the engineering rationale and can be retried. The progress counter measures learning only; it **does not prove** a real deployment occurred.

## Predict → inspect → execute safely → verify

1. **Predict** the behavior before reading the answer.
2. **Inspect** the read-only snapshot of real local Docker, Kubernetes, or GitHub results, along with the actual source link.
3. **Execute** only through the separate, existing **Live demo** if you want to run the real Docker/GitOps tests. Never run arbitrary commands from a web browser.
4. **Verify** using observed evidence. A successful quiz answer, old CI run, or static explanation is not a live operational proof.

Optional read-only commands are provided for the user's own **trusted terminal** and can be copied. The interface never sends these commands to a server.

## Important architecture boundaries

- The Docker Blue/Green demo is **not** an automatic promotion of the GHCR artifact into Kubernetes.
- GitOps uses an independently reviewed digest-pinned Kubernetes manifest.
- `/health` for the FastAPI dashboard checks process health; its `/ready` additionally checks authentication and PostgreSQL connectivity. The minimal Docker demo service is a separate service.
- PostgreSQL PVC **Bound** does not prove tested backups or disaster recovery.
- Live status is drawn from existing read-only `/api/overview`; absent data is **Not observed**, never represented as verified.
- Progress and answers live only in JavaScript memory and reset on page reload or console lock. No tracking, analytics, localStorage, account data, new API, shell endpoint, or elevated permission is added.
- This is local Linux demonstration software, not an internet-facing production environment.

The existing guided six-stage release walkthrough and guarded Docker/GitOps drills remain unchanged.