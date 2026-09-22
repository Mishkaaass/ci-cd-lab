# Deployment Control UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn OpsBoard into an interactive deployment control plane with real deploy, failed-deploy protection, rollback, and a live deployment timeline.

**Architecture:** The browser sends only approved deployment actions to OpsBoard. OpsBoard stores operation state and deployment steps in PostgreSQL, while execution is isolated behind a small allow-listed runner interface. The UI polls operation state and displays real progress from the backend.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Jinja2, JavaScript, Docker, Nginx, Bash.

**Spec:** Existing OpsBoard blue/green deployment architecture.

## Global Constraints

- No arbitrary shell commands from browser input.
- No fake deployment results or fake telemetry.
- Healthy deploy must pass readiness and production verification.
- Broken deploy must never switch production traffic.
- Rollback must verify the previous slot before switching traffic.
- Every feature follows RED -> GREEN -> verification.
- Existing CI/CD and tests must remain green.
- Public-demo security will not expose unrestricted Docker access.

## Review Focus

- Two deployment requests at the same time must not run concurrently.
- Broken candidate must leave production unchanged.
- Unknown deployment action must be rejected.
- Runner failure must be recorded as a failed operation.
- Browser refresh must preserve operation state because PostgreSQL is the source of truth.

---

### Task 1: Deployment Operation Data Model

Create database-backed deployment operations and timeline steps.

Files:
- Modify: opsboard/models.py
- Modify: opsboard/schemas.py
- Create: opsboard/operations.py
- Create: tests/test_operations.py

Flow:
RED -> model/service tests fail
GREEN -> persistence implementation
Verify -> full pytest + Ruff
Commit -> feat: add deployment operation tracking

---

### Task 2: Safe Deployment Runner

Create an allow-listed runner that maps approved actions to fixed scripts.

Files:
- Create: opsboard/deployment_runner.py
- Create: tests/test_deployment_runner.py

Allowed actions:
- deploy_healthy
- deploy_broken
- rollback

Rules:
- User input can never become a shell command.
- subprocess receives an argument list, never shell=True.
- Unknown actions are rejected.
- Output and exit code are captured.

Commit -> feat: add safe deployment runner

---

### Task 3: Deployment Control API

Add endpoints:

POST /api/operations/deploy-healthy
POST /api/operations/deploy-broken
POST /api/operations/rollback
GET  /api/operations/{id}
GET  /api/operations

Behavior:
- Reject a second active deployment.
- Persist queued/running/success/failed state.
- Persist timeline steps.
- Return operation ID immediately.

Files:
- Modify: app.py
- Modify: opsboard/operations.py
- Create: tests/test_operation_api.py

Commit -> feat: add deployment control API

---

### Task 4: Background Execution

Execute approved operations outside the HTTP request lifecycle.

Timeline example:
1. Candidate selected
2. Container started
3. Readiness check
4. Release identity verified
5. Nginx configuration validated
6. Traffic switched
7. Production converged

Failure example:
1. Candidate selected
2. Container started
3. Readiness failed
4. Production protected

Files:
- Create: opsboard/operation_executor.py
- Create: tests/test_operation_executor.py
- Modify: app.py

Commit -> feat: execute deployment operations asynchronously

---

### Task 5: Interactive OpsBoard UI

Add:
- Deploy Healthy button
- Deploy Broken button
- Rollback button
- Active production release
- BLUE/GREEN slot display
- Live deployment timeline
- Operation result
- Clear production-protected messaging

Files:
- Modify: templates/dashboard.html
- Modify: static/styles.css
- Create: static/dashboard.js
- Modify: app.py
- Modify: tests/test_dashboard.py

The UI polls operation state instead of inventing progress.

Commit -> feat: add interactive deployment controls

---

### Task 6: End-to-End Verification

Verify:

Broken release:
candidate -> readiness fails -> no traffic switch

Healthy release:
candidate -> readiness passes -> Nginx switches -> production verified

Rollback:
previous slot ready -> traffic switches back -> production verified

Quality gates:
- bash -n scripts/deploy.sh
- bash -n scripts/rollback.sh
- python -m pytest -q
- python -m ruff check .
- python -m ruff format --check .
- Docker build
- CI
- CD

Commit/PR only after all verification passes.
