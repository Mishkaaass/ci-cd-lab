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
    """Reuse the user's already verified demo1 checkout when it owns 8080."""
    candidates = sorted(
        (server.STATE / "opsboard-project1-finish/checkouts").glob(
            "demo1-*/scripts/reviewer.sh"
        ),
        reverse=True,
    )
    for script in candidates:
        root = script.parent.parent
        if (root / "scripts/lab.sh").is_file() and (root / "compose.yml").is_file():
            try:
                with urlopen("http://127.0.0.1:8080/version", timeout=0.6) as response:
                    live = json.load(response)
                if isinstance(live, dict) and live.get("version"):
                    return root
            except OSError, URLError, ValueError:
                pass
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


def prepare_labs(docker_root: Path, progress: Progress) -> None:
    # Run only after the local UI starts, so any sudo prompt is visible there.
    progress.data["status"] = "preparing"
    progress.data["summary"] = "Preparing local demo services"
    progress.publish()
    progress.terminal(
        "system",
        "Preparing the local lab; existing volumes are preserved",
        kind="notice",
    )
    print("Preparing local demonstration (volumes preserved)...", flush=True)
    if not socket_open(8080):
        progress.terminal("docker", "$ bash scripts/lab.sh demo", kind="command")
        if not authorized_for_docker(progress):
            progress.note("docker", "Local Docker lab unavailable", "error")
        else:
            code = run_command(
                ["bash", "scripts/lab.sh", "demo"], docker_root, 300, command_env()
            )
            progress.note(
                "docker",
                "Docker lab started"
                if code == 0
                else "Docker lab startup needs attention",
                "success" if code == 0 else "error",
            )
            progress.terminal(
                "docker",
                "Docker lab ready" if code == 0 else "Docker lab needs attention",
                kind="notice",
            )
    else:
        progress.note("docker", "Existing Docker lab reused", "success")
        progress.terminal(
            "docker",
            "Existing Docker lab detected on 127.0.0.1:8080",
            kind="notice",
        )
    # Check first; a new GitOps cluster is never created by a GET or a web action.
    if server.KCFG.is_file():
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
        progress.note(
            "gitops",
            "Dedicated GitOps lab ready"
            if code == 0
            else "GitOps initialization needs attention",
            "success" if code == 0 else "error",
        )
    else:
        progress.note("gitops", "GitOps prerequisites unavailable", "info")
    if progress.data.get("attention") is None and progress.data["status"] != "failed":
        progress.data["status"] = "idle"
        progress.data["summary"] = "Ready. Choose a guarded demonstration above."
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
        print("Local token path:", server.TOKEN_FILE, flush=True)
        print(
            "Open Live Demo, then click Run full showcase. Leave this terminal open.",
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
                progress.data["status"] = "running"
                progress.publish()
                request_file.unlink(missing_ok=True)
                action = request.get("action")
                if action in ACTIONS:
                    progress.begin(action)
                    outcomes = []
                    for sub in ["docker", "gitops"] if action == "all" else [action]:
                        progress.data["status"] = "running"
                        progress.data["summary"] = f"Executing {sub.upper()} lab drill"
                        progress.publish()
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
