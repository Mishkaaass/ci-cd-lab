"""Bearer authorization and bounded HTTP controls for the internal dashboard."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import JSONResponse

MAX_BODY_BYTES = 16 * 1024
MAX_CONFIG_BYTES = 64 * 1024
BODY_TIMEOUT_SECONDS = 10.0
MAX_RATE_KEYS = 1024
EXECUTION_PATHS = {
    "/api/operations/deploy-healthy",
    "/api/operations/deploy-broken",
    "/api/operations/rollback",
}
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9._~-]{32,256}")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
DIGEST_PATTERN = re.compile(r"[a-f0-9]{64}")
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)
SECURITY_HEADERS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "cache-control": "no-store",
}
AUDIT = logging.getLogger("opsboard.audit")
AUDIT.setLevel(logging.INFO)
if not AUDIT.handlers:
    AUDIT.addHandler(logging.StreamHandler())


class SecurityConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Actor:
    name: str
    role: str
    token_sha256: str
    expires_at: int


def credentials() -> list[Actor]:
    """Read a small, rotatable private configuration; never cache usable tokens."""
    filename = os.getenv("OPSBOARD_AUTH_FILE", "")
    try:
        if not filename or not Path(filename).is_file():
            raise SecurityConfigurationError
        with Path(filename).open(encoding="utf-8") as handle:
            content = handle.read(MAX_CONFIG_BYTES + 1)
        if len(content) > MAX_CONFIG_BYTES:
            raise SecurityConfigurationError
        entries = json.loads(content)
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise SecurityConfigurationError
        result = []
        names = set()
        digests = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "name",
                "role",
                "token_sha256",
                "expires_at",
            }:
                raise SecurityConfigurationError
            name, role = entry["name"], entry["role"]
            digest, expiry = entry["token_sha256"], entry["expires_at"]
            if (
                not isinstance(name, str)
                or not NAME_PATTERN.fullmatch(name)
                or role not in ("viewer", "operator")
                or not isinstance(digest, str)
                or not DIGEST_PATTERN.fullmatch(digest)
                or type(expiry) is not int
                or expiry <= 0
                or name in names
                or digest in digests
            ):
                raise SecurityConfigurationError
            names.add(name)
            digests.add(digest)
            result.append(Actor(name, role, digest, expiry))
        return result
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise SecurityConfigurationError(
            "Authentication configuration unavailable"
        ) from exc


def authentication_ready() -> bool:
    try:
        return any(actor.expires_at > time.time() for actor in credentials())
    except SecurityConfigurationError:
        return False


def deployments_enabled() -> bool:
    return os.getenv("OPSBOARD_ENABLE_DEPLOYMENTS", "false") == "true"


def authenticate(values: list[str]) -> Actor | None:
    if len(values) != 1:
        return None
    parts = values[0].split(" ")
    if (
        len(parts) != 2
        or parts[0].lower() != "bearer"
        or not TOKEN_PATTERN.fullmatch(parts[1])
    ):
        return None
    candidates = credentials()
    digest = hashlib.sha256(parts[1].encode("ascii")).hexdigest()
    found = None
    for actor in candidates:
        if (
            hmac.compare_digest(digest, actor.token_sha256)
            and actor.expires_at > time.time()
        ):
            found = actor
    return found


bearer_scheme = HTTPBearer(auto_error=False)


def require_actor(
    request: Request,
    _credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_scheme)
    ],
) -> Actor:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        raise HTTPException(
            401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
        )
    return actor


class RequestLimiter:
    """Bounded, thread-safe, per-process fixed windows; not a distributed limiter."""

    def __init__(self):
        self._windows = OrderedDict()
        self._lock = Lock()

    def clear(self):
        with self._lock:
            self._windows.clear()

    def allow(self, key: str, limit: int) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            # Entries retain creation order; reading never extends a window.
            while self._windows:
                first_key, (started, _count) = next(iter(self._windows.items()))
                if now - started < 60:
                    break
                del self._windows[first_key]
            if key not in self._windows:
                if len(self._windows) >= MAX_RATE_KEYS:
                    return False, 60
                self._windows[key] = (now, 0)
            started, count = self._windows[key]
            retry = max(1, math.ceil(60 - (now - started)))
            if count >= limit:
                return False, retry
            self._windows[key] = (started, count + 1)
            return True, retry


def allowed_host(values: list[str]) -> bool:
    if len(values) != 1 or len(values[0]) > 255:
        return False
    raw = values[0]
    if any(char in raw for char in "/\\@,#? \t\r\n"):
        return False
    try:
        parsed = urlsplit("http://" + raw)
        hostname = parsed.hostname
        if not hostname or parsed.netloc != raw:
            return False
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        if ":" in hostname:
            ipaddress.IPv6Address(hostname)
        elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", hostname):
            return False
    except ValueError:
        return False
    allowed = os.getenv("OPSBOARD_ALLOWED_HOSTS", "localhost,127.0.0.1,opsboard,::1")
    return hostname.lower() in {value.strip().lower() for value in allowed.split(",")}


class SecurityMiddleware:
    def __init__(self, app, limiter: RequestLimiter):
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        method = scope["method"]
        private = path.startswith("/api/") or path == "/api"
        state = scope.setdefault("state", {})
        state["request_id"] = uuid.uuid4().hex
        actor = None
        status = 500

        def header_values(name):
            return [
                v.decode("latin-1") for k, v in scope["headers"] if k.lower() == name
            ]

        async def secured_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _v in headers}
                for name, value in SECURITY_HEADERS.items():
                    if name.encode() not in present:
                        headers.append((name.encode(), value.encode()))
                headers.append((b"x-request-id", state["request_id"].encode()))
                message = {**message, "headers": headers}
            await send(message)

        async def reject(code, detail, extra=None):
            response = JSONResponse({"detail": detail}, status_code=code, headers=extra)
            await response(scope, receive, secured_send)

        try:
            if len(path) > 2048 or len(scope.get("query_string", b"")) > 4096:
                await reject(414, "Request target too long")
                return
            if (
                len(scope["headers"]) > 64
                or sum(len(k) + len(v) for k, v in scope["headers"]) > 16384
            ):
                await reject(431, "Request headers too large")
                return
            # Probe Host headers are Pod IPs; these fixed JSON routes generate no URLs.
            if path not in ("/health", "/ready") and not allowed_host(
                header_values(b"host")
            ):
                await reject(400, "Invalid host")
                return
            auth_values = header_values(b"authorization")
            if private or auth_values:
                try:
                    # Missing tokens also fail closed if the configuration is malformed.
                    credentials()
                    actor = authenticate(auth_values)
                    rate = int(os.getenv("OPSBOARD_RATE_LIMIT", "120"))
                    write_rate = int(os.getenv("OPSBOARD_WRITE_RATE_LIMIT", "20"))
                    if not 1 <= rate <= 10000 or not 1 <= write_rate <= 10000:
                        raise ValueError
                except SecurityConfigurationError, ValueError:
                    await reject(503, "Authentication configuration unavailable")
                    return
                if actor is None:
                    client = scope.get("client")
                    key = "anonymous:" + str(client[0] if client else "unknown")
                    allowed, retry = self.limiter.allow(key, min(rate, 30))
                    if not allowed:
                        await reject(
                            429, "Request limit exceeded", {"Retry-After": str(retry)}
                        )
                    else:
                        await reject(
                            401,
                            "Authentication required",
                            {"WWW-Authenticate": "Bearer"},
                        )
                    return
                state["actor"] = actor
                if (
                    private
                    and method not in ("GET", "HEAD")
                    and actor.role != "operator"
                ):
                    await reject(403, "Insufficient permission")
                    return
                if (
                    path.rstrip("/") in EXECUTION_PATHS
                    and method == "POST"
                    and not deployments_enabled()
                ):
                    await reject(
                        503, "Deployment execution is disabled in this runtime"
                    )
                    return
                keys = [("actor:" + actor.name, rate)]
                if method not in ("GET", "HEAD"):
                    keys.append(("write:" + actor.name, min(rate, write_rate)))
                for key, limit in keys:
                    allowed, retry = self.limiter.allow(key, limit)
                    if not allowed:
                        await reject(
                            429, "Request limit exceeded", {"Retry-After": str(retry)}
                        )
                        return

            lengths = header_values(b"content-length")
            if len(lengths) > 1 or (lengths and header_values(b"transfer-encoding")):
                await reject(400, "Ambiguous request framing")
                return
            if lengths:
                if not re.fullmatch(r"[0-9]{1,12}", lengths[0]):
                    await reject(400, "Invalid content length")
                    return
                if int(lengths[0]) > MAX_BODY_BYTES:
                    await reject(413, "Request body too large")
                    return

            body = bytearray()
            deadline = time.monotonic() + BODY_TIMEOUT_SECONDS
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    await reject(408, "Request body timeout")
                    return
                try:
                    message = await asyncio.wait_for(receive(), remaining)
                except TimeoutError:
                    await reject(408, "Request body timeout")
                    return
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    await reject(400, "Invalid request body")
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    await reject(413, "Request body too large")
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            if lengths and len(body) != int(lengths[0]):
                await reject(400, "Content length mismatch")
                return
            replayed = False

            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                return await receive()

            await self.app(scope, replay, secured_send)
        finally:
            if private and (method not in ("GET", "HEAD") or status in (401, 403, 429)):
                AUDIT.info(
                    json.dumps(
                        {
                            "event": "api_request",
                            "request_id": state["request_id"],
                            "actor": actor.name if actor else "anonymous",
                            "method": method,
                            "path": path[:2048],
                            "status": status,
                        }
                    )
                )
