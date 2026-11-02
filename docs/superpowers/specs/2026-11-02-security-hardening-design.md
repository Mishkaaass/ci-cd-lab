# OpsBoard security hardening

## Intent and decisions

Build measurable defenses for the existing internal operations dashboard and its
API, with automated attack regression tests and a reproducible isolated DAST job.
The user requested implementation, short educational steps, preserved data and
complete runnable updates. Audience was not specified: the implementation default
is a small internal team with separate `viewer` and `operator` credentials.

Approaches considered: external OIDC (appropriate future SSO, requires a separate
identity provider); custom password/session login (adds password, cookie and CSRF
lifecycle); opaque bearer credentials (chosen implementation default, no external
account or custom JWT implementation). Do not describe this default as a user
choice. Preserve the future option to replace authentication with OIDC.

## Behavior

- Every `/api/` route requires an unexpired bearer credential. Viewers can read;
  operators can write. Authentication and authorization run before body parsing,
  database access, monitor calls or deployment dispatch. No cookies or query
  parameters authenticate requests. Credential hashes and expirations live in a
  private JSON file outside Git; missing/invalid configuration fails closed.
- Public dashboard navigation returns only a locked, empty shell. The browser
  unlocks with a token, retains it only in JavaScript memory and clears displayed
  private data on lock/expiry. Public health remains available; readiness checks
  valid auth configuration and PostgreSQL. Existing `/version` remains public.
- Local Compose execution is disabled unless explicitly enabled. It remains a
  Compose backend, not Kubernetes deployment control. Reads and recording history
  do not require enabling deployment execution.
- Match input length to database columns; reject NUL/surrogate text and unknown
  fields; bound integer values and paginated reads. Release identifiers must not
  begin with option/path punctuation. Preserve bound ORM queries and output
  encoding. Add request size, body receive deadline and bounded per-process rate
  limits. This is application abuse mitigation, not network DDoS protection.
- Add security headers, host validation and JSON audit events without credentials,
  query strings or request bodies. Keep Swagger usable with restricted CSP.
- Tests cover authorization with no side effects, SQL payload persistence as
  literal data, browser XSS, command arguments, traversal, payload limits, request
  rate limits and fail-closed configuration. Do not claim all attacks are covered.

## CI/CD and deployment

Keep the existing CI workflow as the complete gate used by CD. Add Bandit, IaC
misconfiguration checks, security tests and isolated ZAP API scanning to that
workflow. ZAP's target is a disposable container and database, without host Docker
socket, deployment credentials or executable Compose scripts; exclude operation
execution endpoints from the generic scanner and cover them with targeted tests.
Redact test credentials from retained reports. Add reviewed dependency updates
and pin workflow Actions by verified upstream commit.

Do not silently redeploy the live cluster or rotate its credentials. Provide a
credential bootstrap tool and a separate explicit image-promotion/configuration
step after the new image is built and verified by CD. PR #11 and initial Argo
bootstrap remain pending external actions. Never use an unmerged PR's synthetic
merge SHA as proof of a real merge.

## Explicit limits

No public exposure, third-party attack targets, host firewall/SSH changes,
destructive scan of existing databases, default account/password, authentication
bypass mode or persistent browser token storage. OIDC, distributed rate limiting,
network policy enforcement, database owner/runtime role separation, backup restore
and image signing are follow-on controls, not completed claims. Existing non-root,
read-only application filesystem, capability restrictions and pinned image
digests remain part of the runtime baseline.
