"""Explicitly started local demo supervisor for the two guarded lab drills.

The HTTP process remains unprivileged. It can only place a typed request in a
private directory; this foreground supervisor chooses and executes fixed repo
scripts. No shell input comes from the browser. No Docker socket is passed to
or mounted inside the web process.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from unified_console import server

ROOT = Path(__file__).resolve().parent.parent
STATE = server.STATE / "opsboard-showcase"
MAX_EVENTS = 90
ACTIONS = frozenset({"all", "docker", "gitops"})
MAX_TERMINAL_ROWS = 125


def safe_terminal_output(track: str, line: str) -> str | None:
    """Expose known command output only, never arbitrary process stdout."""
    import re

    value = line.strip()
    if not value or len(value) > 190 or any(ord(c) < 32 for c in value):
        return None
    if track == "docker":
        fixed = {
            "[1/3] Broken candidate: failure is expected",
            "[2/3] Healthy candidate: validated before switching",
            "[3/3] Rollback to original healthy slot",
            "Candidate is READY.",
            "PASS: broken candidate rejected; production release unchanged",
            "PASS: production switched blue -> green",
            "PASS: production switched green -> blue",
            "PASS: broken gate, healthy rollout, exact rollback identity",
            "Candidate failed readiness checks.",
            "Production traffic was NOT changed.",
            "Deployment history recorded.",
            "nginx: the configuration file /etc/nginx/nginx.conf syntax is ok",
            "nginx: configuration file /etc/nginx/nginx.conf test is successful",
        }
        if value in fixed:
            return value
        step = (
            r"OPSBOARD_STEP\|(?:running|success|failed)\|"
            r"(?:Candidate selected|Container started|Readiness check|"
            r"Release identity verified|Nginx configuration validated|"
            r"Traffic switched|Production converged|Rollback target selected|"
            r"Target readiness verified)"
        )
        checks = (
            r"readiness attempt (?:[1-9]|1[0-5])/15 failed",
            r"PASS: traffic switched to healthy release "
            r"good-[0-9]{8,16}\|good[0-9]{8,16}",
            r"Production verified after [1-9][0-9]? attempt\(s\):",
            step,
        )
        if any(re.fullmatch(pattern, value) for pattern in checks):
            return value
    if track == "gitops":
        fixed = {
            "deployment.apps/opsboard scaled",
            "PASS: real GitOps self-healing restored replicas=1",
            "Temporarily scaling OpsBoard to 2 replicas. "
            "Argo CD should restore Git's 1.",
        }
        if value in fixed:
            return value
    return None


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def private_directory(path: Path = STATE) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = path.lstat()
    if path.is_symlink() or not path.is_dir() or st.st_uid != os.getuid():
        raise RuntimeError("Showcase state directory has unsafe ownership/type")
    path.chmod(0o700)
    return path


def atomic_json(path: Path, data: dict) -> None:
    """Only store allowlisted structured status; refuse directory symlinks."""
    private_directory(path.parent)
    if path.is_symlink():
        raise RuntimeError("Refusing to replace linked state file")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 140_000:
        raise RuntimeError("Status is too large")
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path: Path) -> dict | None:
    try:
        st = path.lstat()
        if (
            not path.is_file()
            or path.is_symlink()
            or st.st_uid != os.getuid()
            or st.st_mode & 0o077
            or st.st_size > 140_000
        ):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except OSError, ValueError, UnicodeError:
        return None


def initial_status() -> dict:
    return {
        "enabled": True,
        "status": "idle",
        "action": None,
        "started_at": None,
        "finished_at": None,
        "summary": "Ready for a guided local demonstration",
        "steps": [],
        "terminal": [],
        "attention": None,
        "docker_phase": None,
        "gitops_phase": None,
        "updated_at": timestamp(),
    }


class Progress:
    def __init__(self, path: Path):
        self.path = path
        self.data = initial_status()
        self.publish()

    def publish(self) -> None:
        self.data["updated_at"] = timestamp()
        atomic_json(self.path, self.data)

    def note(
        self, track: str, title: str, kind: str = "info", detail: str = ""
    ) -> None:
        # The caller supplies static descriptions; no untrusted process output.
        self.data["steps"].append(
            {
                "at": timestamp(),
                "track": track,
                "title": title,
                "kind": kind,
                "detail": detail[:110],
            }
        )
        self.data["steps"] = self.data["steps"][-MAX_EVENTS:]
        self.publish()

    def begin(self, action: str) -> None:
        self.data = initial_status()
        self.data.update(
            {
                "status": "running",
                "action": action,
                "started_at": timestamp(),
                "summary": "Real lab operations in progress",
            }
        )
        self.publish()
        self.terminal("system", "$ Run predefined lab demonstration", kind="command")
        self.note(
            "system", "Guided run started", "info", "Using existing guarded lab scripts"
        )

    def finish(self, successful: bool, description: str) -> None:
        self.data.update(
            {
                "status": "passed" if successful else "failed",
                "finished_at": timestamp(),
                "summary": description,
            }
        )
        self.note("system", description, "success" if successful else "error")

    def terminal(self, track: str, content: str, *, kind: str = "output") -> None:
        # Static messages or syntactically allowlisted subprocess lines only.
        # The web endpoint never receives a raw subprocess transcript.
        self.data.setdefault("terminal", []).append(
            {
                "at": timestamp(),
                "track": track,
                "kind": kind,
                "text": content[:190],
            }
        )
        self.data["terminal"] = self.data["terminal"][-MAX_TERMINAL_ROWS:]
        self.publish()

    def attention(self, title: str | None = None, message: str = "") -> None:
        self.data["attention"] = (
            {"kind": "sudo", "title": title, "message": message} if title else None
        )
        self.publish()


def parse_drill_line(progress: Progress, line: str, track: str) -> None:
    """Turn known verified script output into stable evidence, never echo secrets."""
    text = line.strip()
    if track == "docker":
        rules = (
            (
                "[1/3] Broken candidate",
                "broken",
                "Testing rejection of an unhealthy release",
                "info",
            ),
            (
                "PASS: broken candidate rejected; production release unchanged",
                "blocked",
                "Unhealthy candidate rejected; live traffic protected",
                "success",
            ),
            (
                "[2/3] Healthy candidate",
                "healthy",
                "Validating healthy candidate",
                "info",
            ),
            (
                "OPSBOARD_STEP|success|Release identity verified",
                "verified",
                "Version and Git identity verified",
                "success",
            ),
            (
                "PASS: production switched blue -> green",
                "green",
                "Live traffic switched from Blue to Green",
                "success",
            ),
            (
                "PASS: production switched green -> blue",
                "blue",
                "Nginx restored traffic to Blue",
                "success",
            ),
            (
                "PASS: broken gate, healthy rollout, exact rollback identity",
                "complete",
                "Exact version and SHA restored after rollback",
                "success",
            ),
        )
        for needle, phase, title, kind in rules:
            if (
                text == needle
                or (needle.startswith("[2/3]") and text.startswith(needle))
                or (needle.startswith("[1/3]") and text.startswith(needle))
            ):
                progress.data["docker_phase"] = phase
                progress.note(track, title, kind)
                return
    elif track == "gitops":
        rules = (
            (
                "Temporarily scaling OpsBoard to 2 replicas.",
                "drift",
                "Introducing controlled replica drift: 1 to 2",
                "info",
            ),
            (
                "deployment.apps/opsboard scaled",
                "scaled",
                "Kubernetes accepted temporary scaling",
                "info",
            ),
            (
                "PASS: real GitOps self-healing restored replicas=1",
                "restored",
                "Argo CD reconciled desired replicas back to 1",
                "success",
            ),
        )
        for needle, phase, title, kind in rules:
            if text.startswith(needle):
                progress.data["gitops_phase"] = phase
                progress.note(track, title, kind)
                return


def find_existing_docker_root() -> Path:
    """Keep the same dedicated Compose project even when its proxy is stopped.

    Port 8080 alone is not proof of project identity. The dedicated worktree is
    reused first, and its service ownership is verified by Compose later.
    """
    candidates = sorted(
        (server.STATE / "opsboard-project1-finish/checkouts").glob(
            "demo1-*/scripts/reviewer.sh"
        ),
        reverse=True,
    )
    for script in candidates:
        root = script.parent.parent
        if (root / "scripts/lab.sh").is_file() and (root / "compose.yml").is_file():
            return root
    return ROOT


def command_env() -> dict:
    env = os.environ.copy()
    tools = sorted(
        (Path.home() / ".local/share/ci-cd-platform/tools").glob("*/kubectl"),
        reverse=True,
    )
    for tool in tools:
        if tool.is_file() and os.access(tool, os.X_OK):
            env["PATH"] = str(tool.parent) + os.pathsep + env.get("PATH", "")
            break
    return env


def run_command(
    argv: list[str], cwd: Path, timeout: int, env: dict | None = None
) -> int:
    try:
        completed = subprocess.run(argv, cwd=cwd, env=env, timeout=timeout, check=False)
        return completed.returncode
    except OSError, subprocess.TimeoutExpired:
        return 1


def authorized_for_docker(progress: Progress) -> bool:
    """Explicit human authorization, with a visible, time-bounded UI prompt."""
    try:
        probe = subprocess.run(
            ["docker", "info"],
            cwd=ROOT,
            env=command_env(),
            timeout=8,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if probe.returncode == 0:
            return True
    except OSError, subprocess.TimeoutExpired:
        pass
    if run_command(["sudo", "-n", "-v"], ROOT, 4) == 0:
        return True

    title = "Action required: authorize Docker in the terminal"
    message = (
        "Return to the terminal running scripts/showcase.sh and enter your "
        "sudo password there. Typed characters will not appear. "
        "Never enter this password into the browser."
    )
    progress.data["status"] = "waiting_auth"
    progress.data["summary"] = "Waiting for sudo authorization in the terminal"
    progress.attention(title, message)
    progress.terminal(
        "system",
        "AUTHORIZATION REQUIRED — check launcher terminal",
        kind="notice",
    )
    print("\n" + "=" * 64, flush=True)
    print("ACTION REQUIRED: Docker needs sudo authorization.", flush=True)
    print("Type your password HERE (nothing appears as you type).", flush=True)
    print("The browser never receives or stores your password.", flush=True)
    print("=" * 64, flush=True)
    if not sys.stdin.isatty():
        progress.data["status"] = "failed"
        progress.data["summary"] = "Interactive sudo terminal unavailable"
        progress.attention(
            "Interactive terminal required",
            "Start bash scripts/showcase.sh in a real terminal "
            "to authorize Docker; never enter passwords in this browser.",
        )
        progress.note("system", "An interactive terminal is required for sudo", "error")
        return False
    granted = run_command(["sudo", "-v"], ROOT, 120) == 0
    progress.attention()
    progress.data["status"] = (
        "running"
        if granted and progress.data.get("action")
        else "preparing"
        if granted
        else "failed"
    )
    progress.data["summary"] = (
        "Docker authorization granted"
        if granted
        else "Docker authorization was declined or timed out"
    )
    progress.terminal(
        "system",
        "Sudo authorization accepted"
        if granted
        else "Sudo authorization not completed",
        kind="notice",
    )
    progress.publish()
    return granted


def run_drill(action: str, progress: Progress, docker_root: Path) -> bool:
    if action == "docker":
        if not authorized_for_docker(progress):
            progress.note("docker", "Docker authorization was not granted", "error")
            return False
        argv, cwd, deadline = ["bash", "scripts/reviewer.sh", "drill"], docker_root, 300
    else:
        argv, cwd, deadline = (
            ["bash", "scripts/gitops-demo.sh", "drift-test"],
            ROOT,
            240,
        )
        if not server.KCFG.is_file():
            progress.note("gitops", "Dedicated GitOps kubeconfig is missing", "error")
            return False
    progress.note(action, "Executing real guarded lab script", "info")
    progress.terminal(action, "$ " + " ".join(argv), kind="command")
    print("\nRUN:", " ".join(argv), "from", cwd, flush=True)
    process = None
    try:
        # The parent remains interactive for sudo; subprocess stdout is piped
        # only to the terminal and to a strict, credential-free UI allowlist.
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=command_env(),
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        import selectors

        start = time.monotonic()
        assert process.stdout is not None
        pending = b""
        eof = False
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while not eof:
                if time.monotonic() - start > deadline:
                    process.terminate()  # never delete or kill lab resources
                    progress.note(action, "Drill exceeded its timeout", "error")
                    progress.terminal(
                        action, "Drill exceeded its time limit", kind="error"
                    )
                    process.wait(timeout=8)
                    return False
                for key, _ in selector.select(timeout=0.7):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        eof = True
                        break
                    pending += chunk
                    if len(pending) > 64_000:
                        pending = pending[-16_000:]
                    while b"\n" in pending:
                        raw, pending = pending.split(b"\n", 1)
                        line = raw.decode("utf-8", errors="replace")
                        print(line, flush=True)
                        visible = safe_terminal_output(action, line)
                        if visible is not None:
                            progress.terminal(action, visible)
                        parse_drill_line(progress, line, action)
            if pending:
                line = pending.decode("utf-8", errors="replace")
                print(line, flush=True)
                visible = safe_terminal_output(action, line)
                if visible is not None:
                    progress.terminal(action, visible)
                parse_drill_line(progress, line, action)
        code = process.wait(timeout=8)
        expected = (
            progress.data["docker_phase"] == "complete"
            if action == "docker"
            else progress.data["gitops_phase"] == "restored"
        )
        if code != 0 or not expected:
            progress.note(
                action, "Drill did not return the expected verified result", "error"
            )
            return False
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        progress.note(
            action,
            "Unable to finish the guarded drill",
            "error",
            type(exc).__name__,
        )
        return False
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()


def socket_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def start_legacy_api(docker_root: Path, state: Path) -> subprocess.Popen | None:
    if socket_open(18001):
        print("Docker history API: existing port 18001 retained", flush=True)
        return None
    log = (state / "docker-api.log").open("ab")
    child = subprocess.Popen(
        ["bash", "scripts/reviewer.sh", "dashboard"],
        cwd=docker_root,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=command_env(),
    )
    log.close()
    for _ in range(60):
        if socket_open(18001):
            print("Docker history API: ready", flush=True)
            return child
        if child.poll() is not None:
            break
        time.sleep(1)
    print("Docker history API not ready; see private state/docker-api.log", flush=True)
    return child


REQUIRED_DOCKER_SERVICES = frozenset({"db", "demo-blue", "demo-green", "nginx"})


def compose_services_ready(docker_root: Path) -> bool:
    """Verify this Compose project's containers, not merely a listening port.

    `sudo -n` never prompts from an unattended health check. Both JSON-array
    and line-delimited Compose v2 output formats are accepted.
    """
    if not (docker_root / "compose.yml").is_file():
        return False
    try:
        info = subprocess.run(
            ["docker", "info"],
            cwd=docker_root,
            env=command_env(),
            capture_output=True,
            timeout=8,
            check=False,
        )
        prefix = ["docker"] if info.returncode == 0 else ["sudo", "-n", "docker"]
        result = subprocess.run(
            [*prefix, "compose", "ps", "--all", "--format", "json"],
            cwd=docker_root,
            env=command_env(),
            capture_output=True,
            timeout=12,
            check=False,
        )
        if result.returncode or not 0 < len(result.stdout) < 64_000:
            return False
        source = result.stdout.decode("utf-8")
        try:
            parsed = json.loads(source)
            rows = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            rows = [json.loads(line) for line in source.splitlines() if line.strip()]
        states = {}
        for row in rows:
            if not isinstance(row, dict):
                return False
            service = row.get("Service")
            if service not in REQUIRED_DOCKER_SERVICES:
                continue
            if service in states:
                return False
            running = str(row.get("State", "")).lower() == "running"
            health = str(row.get("Health", "")).lower()
            healthy = (
                health == "healthy" if service != "nginx" else health in ("", "healthy")
            )
            states[service] = running and healthy
        return len(states) == len(REQUIRED_DOCKER_SERVICES) and all(states.values())
    except OSError, ValueError, UnicodeError, subprocess.TimeoutExpired:
        return False


def docker_lab_ready(docker_root: Path) -> bool:
    """Compose readiness plus *real* loopback proxy readiness and identity."""
    if not compose_services_ready(docker_root):
        return False
    try:
        with urlopen("http://127.0.0.1:8080/ready", timeout=2) as response:
            if response.status != 200:
                return False
        with urlopen("http://127.0.0.1:8080/version", timeout=2) as response:
            if response.status != 200:
                return False
            live = json.load(response)
        return (
            isinstance(live, dict)
            and bool(live.get("version"))
            and bool(live.get("git_sha"))
            and live.get("mode") == "healthy"
        )
    except OSError, URLError, ValueError, TypeError:
        return False


def ensure_docker_lab(docker_root: Path, progress: Progress) -> bool:
    """Fail-closed, idempotent preparation before the startup and every drill.

    Repair is limited to `scripts/lab.sh demo` from the selected local checkout.
    No arbitrary browser command, volume deletion or context switch is allowed.
    """
    if not authorized_for_docker(progress):
        progress.note("docker", "Docker authorization is required", "error")
        return False
    if docker_lab_ready(docker_root):
        progress.note(
            "docker", "Four Compose services and live proxy verified", "success"
        )
        return True
    progress.note(
        "docker",
        "Docker lab incomplete: preparing required Compose services",
        "info",
    )
    progress.terminal(
        "docker",
        "Checking db, demo-blue, demo-green and nginx",
        kind="notice",
    )
    progress.terminal("docker", "$ bash scripts/lab.sh demo", kind="command")
    print("Docker lab incomplete. Starting only the local Compose demo...", flush=True)
    code = run_command(
        ["bash", "scripts/lab.sh", "demo"], docker_root, 300, command_env()
    )
    if code != 0:
        progress.note("docker", "Local Docker lab startup failed", "error")
        progress.terminal(
            "docker",
            "Docker preparation failed; inspect launcher terminal",
            kind="error",
        )
        return False
    # Containers commonly report `health: starting` immediately after Compose up.
    for _ in range(40):
        if docker_lab_ready(docker_root):
            progress.note(
                "docker",
                "All four Compose services and live proxy ready",
                "success",
            )
            progress.terminal("docker", "Docker readiness verified", kind="notice")
            return True
        time.sleep(1)
    progress.note("docker", "Docker readiness check timed out", "error")
    progress.terminal(
        "docker",
        "Compose startup finished but required services are not healthy",
        kind="error",
    )
    return False


def prepare_labs(docker_root: Path, progress: Progress) -> None:
    # UI is already listening. A sudo request is published before prompting.
    progress.data["status"] = "preparing"
    progress.data["summary"] = "Checking local Docker and GitOps prerequisites"
    progress.publish()
    progress.terminal(
        "system",
        "Preparing the local lab; existing volumes are preserved",
        kind="notice",
    )
    print("Preparing local demonstration (volumes preserved)...", flush=True)
    docker_ok = ensure_docker_lab(docker_root, progress)

    # The dedicated cluster is never changed by an ordinary dashboard GET.
    gitops_ok = False
    if server.KCFG.is_file():
        gitops_ok = True
        progress.note("gitops", "Dedicated kind kubeconfig detected", "success")
        progress.terminal(
            "gitops",
            "Dedicated kind cluster configuration detected",
            kind="notice",
        )
    elif server.find_command("kubectl") and server.find_command("kind"):
        progress.note("gitops", "Initializing the dedicated local kind lab", "info")
        progress.terminal("gitops", "$ bash scripts/gitops-demo.sh up", kind="command")
        print("Creating only the dedicated kind-opsboard-review lab...", flush=True)
        code = run_command(
            ["bash", "scripts/gitops-demo.sh", "up"], ROOT, 900, command_env()
        )
        gitops_ok = code == 0 and server.KCFG.is_file()
        progress.note(
            "gitops",
            "Dedicated GitOps lab initialized"
            if gitops_ok
            else "GitOps initialization needs attention",
            "success" if gitops_ok else "error",
        )
    else:
        progress.note("gitops", "GitOps tools are not installed", "info")
    # Never show a blanket Ready state while the Docker database is missing.
    if docker_ok and gitops_ok:
        progress.data["status"] = "idle"
        progress.data["summary"] = "Docker and GitOps ready. Run the guided demo."
    elif docker_ok:
        progress.data["status"] = "idle"
        progress.data["summary"] = (
            "Docker ready. GitOps unavailable; check the local cluster."
        )
    else:
        progress.data["status"] = "failed"
        progress.data["summary"] = (
            "Docker lab not ready. See the launcher terminal; retry the demo "
            "after the prerequisites are fixed."
        )
    progress.publish()


def terminate(child: subprocess.Popen | None) -> None:
    if child is None or child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=5)
    except OSError, subprocess.TimeoutExpired:
        pass


def replace_previous_own_viewer(port: int = 18002) -> bool:
    """Replace only this user's *idle* known Python OpsBoard viewer on Linux.

    A foreign listener is never stopped. No broad process-name kill is used;
    the listener socket and exact Python module must both match.
    """
    if not socket_open(port):
        return True
    state = read_json(STATE / "status.json")
    if state and state.get("enabled") and state.get("status") == "running":
        return False
    try:
        inodes = set()
        for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            parts = line.split()
            address, port_hex = parts[1].split(":")
            if address == "0100007F" and int(port_hex, 16) == port and parts[3] == "0A":
                inodes.add(parts[9])
        if len(inodes) != 1:
            return False
        expected_socket = f"socket:[{next(iter(inodes))}]"
        matches = []
        for process in Path("/proc").iterdir():
            if not process.name.isdigit() or int(process.name) == os.getpid():
                continue
            if process.stat().st_uid != os.getuid():
                continue
            args = (process / "cmdline").read_bytes().split(b"\0")
            if not any(
                args[i : i + 2] == [b"-m", b"unified_console.server"]
                for i in range(len(args) - 1)
            ):
                continue
            for fd in (process / "fd").iterdir():
                try:
                    if os.readlink(fd) == expected_socket:
                        matches.append(int(process.name))
                        break
                except OSError:
                    continue
        if len(matches) != 1:
            return False
        old_pid = matches[0]
        os.kill(old_pid, signal.SIGTERM)
        for _ in range(40):
            if not socket_open(port):
                print("Replaced the previous local OpsBoard viewer safely.")
                return True
            time.sleep(0.1)
    except OSError, ValueError:
        return False
    return False


def showcase_request_is_safe(path: Path) -> bool:
    try:
        st = path.lstat()
        return (
            path.is_file()
            and not path.is_symlink()
            and st.st_uid == os.getuid()
            and not st.st_mode & 0o077
        )
    except OSError:
        return False


def approve_drill(action: str) -> bool:
    """Never execute a browser request without foreground terminal consent."""
    if action not in ACTIONS or not sys.stdin.isatty():
        return False
    try:
        answer = input(f"Approve local {action} drill? Type RUN {action} to proceed: ")
    except EOFError:
        return False
    return answer == f"RUN {action}"


def run() -> int:
    os.umask(0o077)
    path = private_directory()
    if not replace_previous_own_viewer(18002):
        print(
            "Port 18002 is occupied by an unknown or active server. "
            "Stop it in its terminal before retrying.",
            file=sys.stderr,
        )
        return 2
    # A request from an interrupted earlier session must never replay on startup.
    old_request = path / "request.json"
    if old_request.exists() or old_request.is_symlink():
        if showcase_request_is_safe(old_request):
            old_request.unlink()
        else:
            raise RuntimeError("Stale request file has unsafe ownership/type")
    progress = Progress(path / "status.json")
    docker_root = find_existing_docker_root()
    print("Docker lab checkout:", docker_root, flush=True)
    # Start the browser BEFORE Docker/cluster preparation or any sudo prompt.
    # It will now show Preparing / Waiting for sudo instead of appearing stuck.
    api = None
    env = command_env()
    env["OPSBOARD_SHOWCASE_DIR"] = str(path)
    log = (path / "console.log").open("ab")
    console = subprocess.Popen(
        [sys.executable, "-m", "unified_console.server", "serve"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.close()
    try:
        for _ in range(60):
            if socket_open(18002):
                break
            if console.poll() is not None:
                raise RuntimeError(
                    "Unified console did not start (see private console.log)"
                )
            time.sleep(0.25)
        else:
            raise RuntimeError("Timed out waiting for unified console")
        print("\nREADY — http://127.0.0.1:18002/", flush=True)
        print("Local viewer token path:", server.TOKEN_FILE, flush=True)
        print("Local operator token path:", server.OPERATOR_TOKEN_FILE, flush=True)
        print(
            "Open Live Demo, provide the operator token, then approve here.",
            flush=True,
        )
        print(
            "Only fixed local demo scripts can run; Ctrl+C stops the supervisor.\n",
            flush=True,
        )
        progress.data["status"] = "preparing"
        progress.data["summary"] = "Preparing the local lab; use this terminal for sudo"
        progress.publish()
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            if shutil.which("xdg-open"):
                subprocess.Popen(
                    ["xdg-open", "http://127.0.0.1:18002/"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        prepare_labs(docker_root, progress)
        api = start_legacy_api(docker_root, path)
        while console.poll() is None:
            request_file = path / "request.json"
            request = read_json(request_file)
            if request is not None:
                action = request.get("action")
                progress.data["status"] = "queued"
                progress.data["summary"] = "Awaiting explicit approval in the terminal"
                progress.publish()
                request_file.unlink(missing_ok=True)
                if not isinstance(action, str) or not approve_drill(action):
                    progress.data["status"] = "idle"
                    progress.data["summary"] = "Drill declined; no drill commands ran"
                    progress.publish()
                    continue
                if action in ACTIONS:
                    progress.begin(action)
                    outcomes = []
                    for sub in ["docker", "gitops"] if action == "all" else [action]:
                        progress.data["status"] = "running"
                        progress.data["summary"] = f"Executing {sub.upper()} lab drill"
                        progress.publish()
                        if sub == "docker":
                            ok = ensure_docker_lab(docker_root, progress)
                            if ok:
                                ok = run_drill(sub, progress, docker_root)
                        else:
                            ok = run_drill(sub, progress, docker_root)
                        outcomes.append(ok)
                    if all(outcomes):
                        progress.finish(
                            True,
                            "Both real drills verified"
                            if action == "all"
                            else "Real drill verified",
                        )
                    else:
                        progress.finish(False, "One or more real drills need attention")
            time.sleep(0.3)
        raise RuntimeError("Unified server stopped unexpectedly")
    except KeyboardInterrupt:
        print(
            "\nStopping local servers; Docker containers, "
            "kind cluster and PVC are preserved."
        )
        return 0
    except RuntimeError as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1
    finally:
        progress.data["enabled"] = False
        progress.publish()
        terminate(console)
        terminate(api)


def main() -> int:
    parser = argparse.ArgumentParser(description="Foreground local OpsBoard showcase")
    parser.add_argument("command", nargs="?", choices=("start",), default="start")
    parser.parse_args()
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
