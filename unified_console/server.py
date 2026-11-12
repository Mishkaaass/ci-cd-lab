"""Unified OpsBoard console. Local-only, read-only, no privileged web actions.

The Docker and GitOps deployments retain separate security boundaries. This
service observes them through loopback HTTP and a pinned, read-only kubectl
context. It never opens the Docker socket, executes a deployment or changes
Kubernetes resources.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from glob import glob
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/assets/style.css": ("style.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
TOKEN_FILE = CONFIG / "ci-cd-lab/unified-console/viewer.token"
KCFG = STATE / "opsboard-gitops-review/kubeconfig"
CLUSTER_CONTEXT = "kind-opsboard-review"
REPO = "Mishkaaass/ci-cd-lab"
MAX_UPSTREAM_BYTES = 256_000
# Deny-by-default CSP, split for readability.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; base-uri 'none'; "
    "script-src 'self'; style-src 'self'; "
    "img-src 'self'; connect-src 'self'; "
    "form-action 'none'; frame-ancestors 'none'; "
    "object-src 'none'"
)
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, object] = {"value": None, "time": 0.0}


def ensure_token(path: Path = TOKEN_FILE) -> str:
    """Create private local token once; never print it or commit it."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.is_symlink():
        raise RuntimeError("Credential directory may not be a symlink")
    parent.chmod(0o700)
    if not path.exists() and not path.is_symlink():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="ascii") as out:
                out.write(secrets.token_urlsafe(40) + "\n")
    stat = path.lstat()
    if (
        path.is_symlink()
        or not path.is_file()
        or stat.st_uid != os.getuid()
        or stat.st_mode & 0o077
    ):
        raise RuntimeError(
            "Token must be a private 0600 regular file owned by this user"
        )
    token = path.read_text(encoding="ascii").strip()
    if len(token) < 40:
        raise RuntimeError("Token file is invalid")
    return token


def find_command(name: str) -> str | None:
    direct = shutil.which(name)
    if direct:
        return direct
    if name == "kubectl":
        candidates = sorted(
            (Path.home() / ".local/share/ci-cd-platform/tools").glob("*/kubectl"),
            reverse=True,
        )
        for path in candidates:
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return None


def json_http(url: str, token_file: Path | None = None) -> dict | list | None:
    """Only call fixed loopback URLs from the server, never user-controlled URLs."""
    if not re.fullmatch(
        r"http://127\.0\.0\.1:(?:8080|8001|8002|18001)/[a-z0-9/?=&_-]+", url
    ):
        return None
    headers = {"Accept": "application/json", "User-Agent": "OpsBoard-Local-Console/1"}
    if token_file is not None:
        try:
            if token_file.is_symlink() or token_file.stat().st_mode & 0o077:
                return None
            token = token_file.read_text(encoding="ascii").strip()
            if not token:
                return None
            headers["Authorization"] = "Bearer " + token
        except OSError, UnicodeError:
            return None
    try:
        with urlopen(Request(url, headers=headers, method="GET"), timeout=2.0) as res:
            if (
                res.status != 200
                or int(res.headers.get("Content-Length") or 0) > MAX_UPSTREAM_BYTES
            ):
                return None
            body = res.read(MAX_UPSTREAM_BYTES + 1)
            if len(body) > MAX_UPSTREAM_BYTES:
                return None
            value = json.loads(body)
            return value if isinstance(value, (dict, list)) else None
    except HTTPError, URLError, OSError, ValueError, TimeoutError:
        return None


def run_readonly(argv: list[str], timeout: float = 6.0) -> dict | None:
    env = os.environ.copy()
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        process = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False, env=env
        )
        if process.returncode or len(process.stdout) > MAX_UPSTREAM_BYTES:
            return None
        value = json.loads(process.stdout)
        return value if isinstance(value, dict) else None
    except OSError, ValueError, subprocess.TimeoutExpired:
        return None


def compact_sha(value: object) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-f]{7,64}", value, flags=re.I
    ):
        return None
    return value[:12]


def _safe_text(value: object, length: int = 100) -> str | None:
    if value is None or not isinstance(value, (str, int, float, bool)):
        return None
    out = str(value).strip()
    return out[:length] if out else None


def find_docker_viewer() -> Path | None:
    override = os.environ.get("OPSBOARD_DOCKER_VIEWER_TOKEN_FILE")
    if override:
        return Path(override)
    candidates = [
        Path(x)
        for x in glob(str(CONFIG / "ci-cd-lab/local-*/credentials/viewer.token"))
    ]
    candidates = [p for p in candidates if p.is_file() and not p.is_symlink()]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def clean_events(raw: object) -> list[dict]:
    if isinstance(raw, dict):
        for key in ("items", "deployments", "results", "data"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        return []
    events = []
    for row in raw[:6]:
        if not isinstance(row, dict):
            continue
        events.append(
            {
                "type": _safe_text(
                    row.get("operation")
                    or row.get("action")
                    or row.get("type")
                    or "Release event",
                    34,
                ),
                "status": _safe_text(row.get("status") or row.get("result"), 30),
                "version": _safe_text(
                    row.get("version") or row.get("target_version"), 60
                ),
                "when": _safe_text(
                    row.get("created_at")
                    or row.get("started_at")
                    or row.get("timestamp"),
                    60,
                ),
            }
        )
    return events


def docker_state() -> dict:
    live = json_http("http://127.0.0.1:8080/version")
    ready = json_http("http://127.0.0.1:8080/ready")
    blue = json_http("http://127.0.0.1:8001/version")
    green = json_http("http://127.0.0.1:8002/version")
    slot = None
    if isinstance(live, dict):
        identity = (live.get("version"), live.get("git_sha"))
        matches = [
            s
            for s, value in (("blue", blue), ("green", green))
            if isinstance(value, dict)
            and (value.get("version"), value.get("git_sha")) == identity
        ]
        if len(matches) == 1:
            slot = matches[0]
    token_file = find_docker_viewer()
    history = (
        json_http("http://127.0.0.1:18001/api/deployments?limit=6", token_file)
        if token_file
        else None
    )
    healthy = (
        isinstance(live, dict)
        and isinstance(ready, dict)
        and ready.get("status") in ("ready", "ok", "healthy")
    )
    return {
        "available": isinstance(live, dict),
        "healthy": healthy,
        "version": _safe_text(live.get("version"), 64)
        if isinstance(live, dict)
        else None,
        "git_sha": _safe_text(live.get("git_sha"), 64)
        if isinstance(live, dict)
        else None,
        "slot": slot,
        "slots": {
            "blue": {
                "up": isinstance(blue, dict),
                "version": _safe_text(blue.get("version"), 64)
                if isinstance(blue, dict)
                else None,
            },
            "green": {
                "up": isinstance(green, dict),
                "version": _safe_text(green.get("version"), 64)
                if isinstance(green, dict)
                else None,
            },
        },
        "events": clean_events(history),
        "events_available": history is not None,
    }


def kube_get(kubectl: str | None, namespace: str, kind: str, name: str) -> dict | None:
    if not kubectl or not KCFG.is_file():
        return None
    return run_readonly(
        [
            kubectl,
            "--kubeconfig",
            str(KCFG),
            "--context",
            CLUSTER_CONTEXT,
            "-n",
            namespace,
            "get",
            kind,
            name,
            "-o",
            "json",
        ],
        timeout=7.0,
    )


def kubernetes_state() -> dict:
    kubectl = find_command("kubectl")
    app = kube_get(kubectl, "argocd", "application", "opsboard")
    if app is None:
        return {
            "available": False,
            "sync": None,
            "health": None,
            "revision": None,
            "desired": None,
            "ready": None,
            "image": None,
            "pvc": None,
        }
    dep = kube_get(kubectl, "opsboard", "deployment", "opsboard")
    pvc = kube_get(kubectl, "opsboard", "pvc", "data-postgres-0")
    status = app.get("status", {}) if isinstance(app, dict) else {}
    sync = status.get("sync", {}) if isinstance(status, dict) else {}
    health = status.get("health", {}) if isinstance(status, dict) else {}
    spec = dep.get("spec", {}) if isinstance(dep, dict) else {}
    dep_status = dep.get("status", {}) if isinstance(dep, dict) else {}
    images = []
    for container in spec.get("template", {}).get("spec", {}).get("containers", []):
        if isinstance(container, dict) and container.get("image"):
            images.append(_safe_text(container["image"], 200))
    claim = pvc.get("status", {}) if isinstance(pvc, dict) else {}
    return {
        "available": isinstance(app, dict) and isinstance(dep, dict),
        "sync": _safe_text(sync.get("status")) if isinstance(sync, dict) else None,
        "health": _safe_text(health.get("status"))
        if isinstance(health, dict)
        else None,
        "revision": compact_sha(sync.get("revision"))
        if isinstance(sync, dict)
        else None,
        "desired": spec.get("replicas")
        if isinstance(spec.get("replicas"), int)
        else None,
        "ready": dep_status.get("readyReplicas", 0)
        if isinstance(dep_status, dict)
        else None,
        "image": images[0] if images else None,
        "pvc": _safe_text(claim.get("phase")) if isinstance(claim, dict) else None,
    }


def github_state() -> dict:
    gh = find_command("gh")
    if not gh:
        return {
            "available": False,
            "conclusion": None,
            "sha": None,
            "url": None,
            "jobs": [],
        }
    runs = run_readonly(
        [
            gh,
            "api",
            f"repos/{REPO}/actions/workflows/ci.yml/runs?branch=main&per_page=1",
        ],
        timeout=8.0,
    )
    workflows = runs.get("workflow_runs") if isinstance(runs, dict) else None
    run = workflows[0] if isinstance(workflows, list) and workflows else None
    if not isinstance(run, dict):
        return {
            "available": False,
            "conclusion": None,
            "sha": None,
            "url": None,
            "jobs": [],
        }
    jobs = (
        run_readonly(
            [gh, "api", f"repos/{REPO}/actions/runs/{run.get('id')}/jobs?per_page=100"],
            timeout=8.0,
        )
        if isinstance(run.get("id"), int)
        else None
    )
    names = []
    if isinstance(jobs, dict) and isinstance(jobs.get("jobs"), list):
        for job in jobs["jobs"]:
            if isinstance(job, dict) and str(job.get("name", "")).startswith("CI/"):
                names.append(
                    {
                        "name": _safe_text(job.get("name"), 64),
                        "result": _safe_text(
                            job.get("conclusion") or job.get("status"), 32
                        ),
                    }
                )
    url = run.get("html_url")
    if not isinstance(url, str) or not re.fullmatch(
        r"https://github\.com/Mishkaaass/ci-cd-lab/actions/runs/\d+", url
    ):
        url = None
    return {
        "available": True,
        "conclusion": _safe_text(run.get("conclusion") or run.get("status"), 32),
        "sha": compact_sha(run.get("head_sha")),
        "url": url,
        "jobs": names[:12],
    }


def collect() -> dict:
    # Independent read-only sources run concurrently; an offline cluster must
    # not delay Docker data and vice versa.
    with ThreadPoolExecutor(max_workers=3) as pool:
        docker = pool.submit(docker_state)
        kube = pool.submit(kubernetes_state)
        github = pool.submit(github_state)
        return {
            "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "scope": "local-lab",
            "read_only": True,
            "docker": docker.result(),
            "kubernetes": kube.result(),
            "ci": github.result(),
        }


def snapshot() -> dict:
    with _CACHE_LOCK:
        if (
            isinstance(_CACHE["value"], dict)
            and time.monotonic() - float(_CACHE["time"]) < 12
        ):
            return _CACHE["value"]  # type: ignore[return-value]
        value = collect()
        _CACHE["value"] = value
        _CACHE["time"] = time.monotonic()
        return value


class Handler(BaseHTTPRequestHandler):
    server_version = "OpsBoardLocal"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, _fmt: str, *_args: object) -> None:
        # No access logs: never risk logging credentials or sensitive query data.
        return

    def respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            CONTENT_SECURITY_POLICY,
        )
        self.end_headers()
        self.wfile.write(body)

    def error(self, status: int, message: str) -> None:
        data = json.dumps({"error": message}, separators=(",", ":")).encode("utf-8")
        self.respond(status, data, "application/json; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        self.error(HTTPStatus.METHOD_NOT_ALLOWED, "This console is read-only")

    def do_GET(self) -> None:  # noqa: N802
        actual_port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (
            f"127.0.0.1:{actual_port}",
            f"localhost:{actual_port}",
        ):
            self.error(HTTPStatus.BAD_REQUEST, "Invalid host")
            return
        origin = self.headers.get("Origin")
        if origin and origin not in (
            f"http://127.0.0.1:{actual_port}",
            f"http://localhost:{actual_port}",
        ):
            self.error(HTTPStatus.FORBIDDEN, "Invalid origin")
            return
        path = self.path
        if path == "/api/overview":
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer ") or not hmac.compare_digest(
                authorization[7:], self.server.viewer_token
            ):  # type: ignore[attr-defined]
                self.error(HTTPStatus.UNAUTHORIZED, "Viewer token required")
                return
            try:
                payload = json.dumps(snapshot(), separators=(",", ":")).encode("utf-8")
            except Exception:
                self.error(
                    HTTPStatus.SERVICE_UNAVAILABLE, "Status temporarily unavailable"
                )
                return
            self.respond(HTTPStatus.OK, payload, "application/json; charset=utf-8")
            return
        if path in ASSETS:
            name, content_type = ASSETS[path]
            try:
                self.respond(HTTPStatus.OK, (HERE / name).read_bytes(), content_type)
            except OSError:
                self.error(HTTPStatus.INTERNAL_SERVER_ERROR, "Asset missing")
            return
        self.error(HTTPStatus.NOT_FOUND, "Not found")


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], token: str):
        self.viewer_token = token
        super().__init__(address, Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified local OpsBoard, read-only")
    parser.add_argument(
        "action", nargs="?", choices=("serve", "doctor", "token"), default="serve"
    )
    parser.add_argument("--port", type=int, default=18002)
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        parser.error("Port must be 1024-65535")
    token = ensure_token()
    if args.action == "token":
        if not sys.stdout.isatty():
            raise SystemExit("Refusing to print a credential to non-interactive output")
        print(token)
        return 0
    if args.action == "doctor":
        print("Console: ready; local credentials: private")
        print("Docker live URL: http://127.0.0.1:8080/version")
        print("Kubernetes kubeconfig:", "present" if KCFG.is_file() else "missing")
        print("kubectl:", "found" if find_command("kubectl") else "missing")
        print("GitHub CLI:", "found" if find_command("gh") else "missing")
        return 0
    try:
        with LocalServer(("127.0.0.1", args.port), token) as server:
            print(f"OpsBoard unified: http://127.0.0.1:{args.port}/")
            print(f"Viewer token (private local file): {TOKEN_FILE}")
            print("Read-only. Ctrl+C to stop. No Docker or Kubernetes changes.")
            server.serve_forever(poll_interval=0.4)
    except OSError as exc:
        print(f"Cannot bind local port {args.port}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
