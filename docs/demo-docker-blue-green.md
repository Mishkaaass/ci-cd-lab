# Demo 1 | Docker Blue/Green — start here

**What you're proving:** A new version is tested **before** it receives traffic. A broken version is rejected. A successful deployment can be rolled back to the **exact original version**.

**How it works:** Docker runs a Blue and a Green copy of the demo app. Nginx sends requests to **one** copy. The deploy script prepares the inactive copy, checks `/ready` and `/version`, and only then switches Nginx. The dashboard displays status and the operation history; it does **not** run Docker commands itself.

## Before you start

- **Linux** machine with Git, Bash and `curl`.
- **Python 3.14** (including `venv`), **Docker Engine** and **Docker Compose** plugin installed and running.
- Ports `18001` (dashboard), `8080` (Nginx), `5432` (PostgreSQL), `8001` and `8002` available.
- Docker permissions. If your user requires `sudo docker`, run `sudo -v` in the terminal where you run deployment commands.

### 1. Download (once)

```bash
git clone https://github.com/Mishkaaass/ci-cd-lab.git
cd ci-cd-lab
bash scripts/reviewer.sh doctor
```

Check the output: if a requirement is shown as `MISSING`, install it **before continuing**. `doctor` is an information check; it does not install tools.

### 2. Terminal A — start the dashboard

```bash
bash scripts/reviewer.sh dashboard
```

Wait for `Uvicorn running on http://127.0.0.1:18001`. **Leave Terminal A open.** Open [http://127.0.0.1:18001/dashboard](http://127.0.0.1:18001/dashboard).

### 3. Terminal B — start the demo services

Open a **second terminal**, `cd` to the **same** `ci-cd-lab` directory, then:

```bash
bash scripts/reviewer.sh up
bash scripts/reviewer.sh status
```

If Docker asks for a Linux password, that is for local `sudo`. If you get a noninteractive sudo error, run `sudo -v` **in Terminal B**, then retry the command that failed. Don't run the entire checkout under `sudo`.

Expected: PostgreSQL, Blue, Green and Nginx start; `http://127.0.0.1:8080/ready` succeeds. The version at `http://127.0.0.1:8080/version` is the **currently live** release.

### 4. Unlock the dashboard (view-only)

In Terminal B:

```bash
bash scripts/reviewer.sh tokens
```

This prints **file paths**, not token values. Read the viewer token **locally**, paste it in the Dashboard **Unlock** form, and keep it private. The web deployment buttons stay disabled by design. **Terminal commands** are the authorized demo controls.

### 5. Run the full deployment drill

```bash
bash scripts/reviewer.sh drill
```

| Step | What happens | What proves success |
| --- | --- | --- |
| **1. Broken** | Candidate's readiness fails. | **Old live traffic does not change.** |
| **2. Healthy** | Inactive container passes readiness and version checks. | Nginx **switches** to the new release. |
| **3. Rollback** | Nginx switches back to the old ready container. | **Original version + Git SHA** match the starting values. |

The failed **candidate** in step 1 is **intentional**; the full `drill` must end with `PASS: broken gate, healthy rollout, exact rollback identity`. Refresh the dashboard to inspect deployment history.

### 6. Finish safely

- **Check again:** `bash scripts/reviewer.sh status`.
- **Stop dashboard:** `Ctrl+C` in Terminal A. Its local SQLite history and tokens remain.
- **Stop Docker services without deleting data:** from the **same checkout**, run `sudo docker compose stop` (or `docker compose stop` if your user has Docker access).
- **Do not** use `docker compose down -v`: it would remove persistent volumes. Don't force-reset `nginx/active_backend.inc`; it reflects live routing.

**Something fails?** See [Troubleshooting](reviewer-tour.md). If ports are occupied or containers belong to a different checkout, inspect them first; the scripts intentionally stop instead of taking over someone else's services.

[← Back to main README](../README.md)
