"""Unified OpsBoard console: local viewer and opt-in guided lab requests.

The unprivileged web server observes Docker, Kubernetes and GitHub. Normally it
is read-only. During an explicitly started, local showcase it can enqueue one
of three fixed requests to an independent foreground supervisor. The web server
never opens a Docker socket, executes a deployment, or changes Kubernetes.
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
    "/assets/learning.js": ("learning.js", "text/javascript; charset=utf-8"),
}
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
TOKEN_FILE = CONFIG / "ci-cd-lab/unified-console/viewer.token"
OPERATOR_TOKEN_FILE = CONFIG / "ci-cd-lab/unified-console/operator.token"
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
            # Job names returned by GitHub are plain names (e.g. "Python tests")
            # and must not be silently hidden behind a hypothetical "CI/" prefix.
            if isinstance(job, dict) and _safe_text(job.get("name"), 64):
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
        "jobs_available": (
            isinstance(jobs, dict) and isinstance(jobs.get("jobs"), list)
        ),
        "jobs": names[:12],
    }


def github_cd_state() -> dict:
    """Read CI and CD workflow evidence and compare complete main commit SHAs.

    This is an independent, read-only GitHub observer. It cannot trigger a
    workflow, mutate the repo or claim that a GHCR digest was verified.
    """
    unavailable = {
        "available": False,
        "status": None,
        "conclusion": None,
        "sha": None,
        "full_sha": None,
        "ci_sha": None,
        "url": None,
        "matches_ci": False,
        "ci_observed": False,
    }
    gh = find_command("gh")
    if not gh:
        return unavailable
    with ThreadPoolExecutor(max_workers=2) as pool:
        latest_ci = pool.submit(
            run_readonly,
            [
                gh,
                "api",
                f"repos/{REPO}/actions/workflows/ci.yml/runs?branch=main&per_page=1",
            ],
            8.0,
        )
        latest_cd = pool.submit(
            run_readonly,
            [
                gh,
                "api",
                f"repos/{REPO}/actions/workflows/cd.yml/runs?branch=main&per_page=1",
            ],
            8.0,
        )
        ci_data = latest_ci.result()
        cd_data = latest_cd.result()

    def first_run(data: object) -> dict | None:
        runs = data.get("workflow_runs") if isinstance(data, dict) else None
        run = runs[0] if isinstance(runs, list) and runs else None
        return run if isinstance(run, dict) else None

    def full_sha(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        if not re.fullmatch(r"[0-9a-f]{40}", value, flags=re.I):
            return None
        return value.lower()

    ci_run = first_run(ci_data)
    cd_run = first_run(cd_data)
    if not cd_run:
        return unavailable
    cd_head = full_sha(cd_run.get("head_sha"))
    ci_head = full_sha(ci_run.get("head_sha")) if ci_run else None
    url = cd_run.get("html_url")
    if not isinstance(url, str) or not re.fullmatch(
        r"https://github\.com/Mishkaaass/ci-cd-lab/actions/runs/[0-9]+", url
    ):
        url = None
    return {
        "available": True,
        "status": _safe_text(cd_run.get("status"), 32),
        "conclusion": _safe_text(cd_run.get("conclusion"), 32),
        "sha": compact_sha(cd_head),
        "full_sha": cd_head,
        "ci_sha": compact_sha(ci_head),
        "url": url,
        "matches_ci": bool(ci_head and cd_head and ci_head == cd_head),
        "ci_observed": bool(ci_head),
    }


def collect() -> dict:
    # Independent read-only sources run concurrently; an offline cluster must
    # not delay Docker data and vice versa.
    with ThreadPoolExecutor(max_workers=4) as pool:
        docker = pool.submit(docker_state)
        kube = pool.submit(kubernetes_state)
        github = pool.submit(github_state)
        cd_future = pool.submit(github_cd_state)
        result = {
            "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "scope": "local-lab",
            "read_only": True,
            "docker": docker.result(),
            "kubernetes": kube.result(),
            "ci": github.result(),
        }
        result["cd"] = cd_future.result()
        return result


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
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.end_headers()
        self.wfile.write(body)

    def error(self, status: int, message: str) -> None:
        data = json.dumps({"error": message}, separators=(",", ":")).encode("utf-8")
        self.respond(status, data, "application/json; charset=utf-8")

    def check_origin_and_host(self) -> bool:
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (
            f"127.0.0.1:{port}",
            f"localhost:{port}",
        ):
            self.error(HTTPStatus.BAD_REQUEST, "Invalid host")
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        ):
            self.error(HTTPStatus.FORBIDDEN, "Invalid origin")
            return False
        return True

    def authenticated(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or not hmac.compare_digest(
            header[7:], self.server.viewer_token
        ):
            self.error(HTTPStatus.UNAUTHORIZED, "Viewer token required")
            return False
        return True

    def showcase_status(self) -> dict:
        # Import lazily: the runner imports this module for existing helpers.
        from unified_console import showcase

        directory = self.server.showcase_directory
        if directory is None:
            return {
                "enabled": False,
                "status": "offline",
                "steps": [],
                "summary": ("Open scripts/showcase.sh to enable guided local drills"),
            }
        value = showcase.read_json(directory / "status.json")
        if value is None:
            return {
                "enabled": False,
                "status": "offline",
                "steps": [],
                "summary": "Local demo supervisor is not responding",
            }
        return value

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/showcase/start":
            self.error(HTTPStatus.METHOD_NOT_ALLOWED, "Unsupported operation")
            return
        if not self.check_origin_and_host() or not self.authenticated():
            self.close_connection = True
            return
        operator = self.server.operator_token
        supplied = self.headers.get("X-OpsBoard-Operator", "")
        if operator is None or not hmac.compare_digest(
            supplied.encode("utf-8"), operator.encode("utf-8")
        ):
            self.error(HTTPStatus.FORBIDDEN, "Separate operator token required")
            self.close_connection = True
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            self.error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/json")
            self.close_connection = True
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        if not 1 <= length <= 128:
            self.error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Invalid request size")
            self.close_connection = True
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except UnicodeError, ValueError:
            self.error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return
        action = payload.get("action") if isinstance(payload, dict) else None
        if action not in ("all", "docker", "gitops"):
            self.error(HTTPStatus.BAD_REQUEST, "Unknown demo action")
            return

        directory = self.server.showcase_directory
        status = self.showcase_status()
        if directory is None or status.get("enabled") is not True:
            self.error(HTTPStatus.FORBIDDEN, "Demo operator is not enabled")
            return
        if status.get("status") in ("queued", "running", "preparing", "waiting_auth"):
            self.error(HTTPStatus.CONFLICT, "Demo already running")
            return
        request_file = directory / "request.json"
        try:
            fd = os.open(
                request_file,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"action": action}, handle)
        except FileExistsError:
            self.error(HTTPStatus.CONFLICT, "Demo request already queued")
            return
        except OSError:
            self.error(HTTPStatus.SERVICE_UNAVAILABLE, "Demo queue unavailable")
            return
        self.respond(
            HTTPStatus.ACCEPTED, b'{"queued":true}', "application/json; charset=utf-8"
        )

    def do_GET(self) -> None:  # noqa: N802
        if not self.check_origin_and_host():
            return
        path = self.path
        if path in ("/api/overview", "/api/showcase/status"):
            if not self.authenticated():
                return
            try:
                result = (
                    snapshot() if path == "/api/overview" else self.showcase_status()
                )
                payload = json.dumps(result, separators=(",", ":")).encode("utf-8")
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

    def __init__(
        self,
        address: tuple[str, int],
        token: str,
        showcase_directory: Path | None = None,
        operator_token: str | None = None,
    ):
        if operator_token is not None and (
            len(operator_token) < 40 or operator_token == token
        ):
            raise ValueError("Operator credential must be separate and strong")
        self.viewer_token = token
        self.operator_token = operator_token if showcase_directory is not None else None
        self.showcase_directory = showcase_directory
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
        demo_directory = None
        if os.environ.get("OPSBOARD_SHOWCASE_DIR"):
            from unified_console import showcase

            demo_directory = showcase.private_directory(
                Path(os.environ["OPSBOARD_SHOWCASE_DIR"])
            )
        operator = ensure_token(OPERATOR_TOKEN_FILE) if demo_directory else None
        with LocalServer(
            ("127.0.0.1", args.port), token, demo_directory, operator
        ) as server:
            print(f"OpsBoard unified: http://127.0.0.1:{args.port}/")
            print(f"Viewer token (private local file): {TOKEN_FILE}")
            print("Local viewer. Privileged operations are not exposed to HTTP.")
            server.serve_forever(poll_interval=0.4)
    except OSError as exc:
        print(f"Cannot bind local port {args.port}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
