# OpsBoard security hardening implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protect and test the OpsBoard API and dashboard without executing attacks against the user's live deployment.

**Architecture:** Opaque bearer credentials with viewer/operator authorization,
an empty unauthenticated dashboard shell, bounded HTTP/input/database reads and
isolated CI security scans. Preserve existing application and Compose behavior
behind explicit authorization and execution enablement.

**Tech Stack:** Python 3.14, FastAPI/Starlette, SQLAlchemy, pytest, browser tests,
Bandit, Trivy and ZAP.

**Spec:** `docs/superpowers/specs/2026-11-02-security-hardening-design.md`

## Global Constraints

- Preserve source upload and user data; never automatically deploy or rotate credentials.
- No default credentials, query/cookie authentication or browser token persistence.
- All new CI jobs must participate in the CI result that gates existing CD.
- Keep docs explicit about test/runtime limits and deferred security controls.

## Review Focus

- Missing/expired/bad credential configuration must never open access.
- Authorization failures must not create records, run monitor calls or dispatch operations.
- Dashboard shell, validation errors, audit logs and reports must not leak credentials or private records.
- Chunked bodies, forged size headers and many rate-limit keys must stay bounded.
- New auth must not leave CD smoke or existing pinned Kubernetes image silently misconfigured.

## Tasks

- [x] Baseline: reproduce the original 52 tests and inspect all request/execution boundaries.
- [x] Authentication/UI: write failing authorization tests, implement bearer roles and locked UI, update existing fixtures explicitly and verify no-side-effect failures.
- [x] HTTP/data guards: write failing validation/limits tests, implement bounds and headers, add attack regression tests for existing ORM and output defenses.
- [x] Pipeline: integrate security jobs and isolated scans into CI, update CD smoke and provide explicit credential/promotion tooling with tests.
- [ ] Verify full Python/browser/security suite, obtain a fresh whole-change review, package a guarded update for the user's repository and document checks requiring their Docker/GitHub environment.

## Verification evidence (2026-11-02)

- Python 3.14.8: 166 tests passed, including all three real Chromium checks.
- Ruff lint/format, JS syntax, shell syntax and Python 3.12 host-script compilation passed.
- Bandit MEDIUM/HIGH confidence/severity gate passed; runtime pip-audit found no known vulnerabilities.
- Independent code review completed; reported Important issues have regression tests and fixes.
- Docker, PostgreSQL-backed suite, actual ZAP execution and GitHub CI/CD remain pending in the user's environment.
- The original 52-test baseline had one environment-specific ps failure; the equivalent OS-API assertion is now portable.
