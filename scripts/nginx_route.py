#!/usr/bin/env python3
"""Bounded, reversible Nginx routing for the local OpsBoard Blue/Green lab.

Usage:
  python3 scripts/nginx_route.py check        # read-only: route matches live traffic
  python3 scripts/nginx_route.py reconcile  # align route to live, no reload
  python3 scripts/nginx_route.py validate      # bounded read-only nginx -t
  python3 scripts/nginx_route.py switch blue  # gated and reversible switch
"""

from __future__ import annotations

import argparse
import fcntl
import http.client
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "nginx" / "active_backend.inc"
PORTS = {"blue": 8001, "green": 8002}
LIVE_PORT = 8080
DOCKER_TIMEOUT_SECONDS = 12


class RouteError(RuntimeError):
    """Fail closed when the live and configured route cannot be verified."""


def emit_step(status: str, name: str) -> None:
    print(f"OPSBOARD_STEP|{status}|{name}", flush=True)


def get_json(port: int, path: str = "/version") -> dict:
    if port not in PORTS.values() and port != LIVE_PORT:
        raise RouteError(f"Unexpected local port {port}")
    if path not in ("/version", "/ready"):
        raise RouteError(f"Unsupported HTTP path {path}")

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", path, headers={"Cache-Control": "no-store"})
        response = connection.getresponse()
        if response.status != 200:
            raise RouteError(f"HTTP {response.status} from port {port}")
        result = json.load(response)
    finally:
        connection.close()

    if not isinstance(result, dict):
        raise RouteError(f"Invalid response from port {port}")
    return result


def release(port: int) -> tuple[str, str]:
    data = get_json(port)
    version, git_sha = data.get("version"), data.get("git_sha")
    if not isinstance(version, str) or not version:
        raise RouteError(f"Missing release version on port {port}")
    if not isinstance(git_sha, str) or not git_sha:
        raise RouteError(f"Missing release git_sha on port {port}")
    return version, git_sha


def observed_live_slot() -> tuple[str, tuple[str, str]]:
    live = release(LIVE_PORT)
    matches = []
    for slot, port in PORTS.items():
        try:
            if release(port) == live:
                matches.append(slot)
        except (OSError, ValueError, RouteError, http.client.HTTPException):
            continue
    if len(matches) != 1:
        raise RouteError(
            "Cannot uniquely identify the live slot from release identities; "
            f"matching slots={matches}. No route changed."
        )
    return matches[0], live


def read_route(handle) -> str:
    handle.seek(0)
    text = handle.read().strip()
    for slot in PORTS:
        if text == f"server demo-{slot}:8000;":
            return slot
    raise RouteError("Unexpected active_backend.inc content; no route changed")


def write_route(handle, slot: str) -> None:
    if slot not in PORTS:
        raise RouteError("Invalid routing slot")
    # In-place write is intentional: Docker binds this FILE's inode into Nginx.
    # os.replace() would leave the container reading the old inode.
    handle.seek(0)
    handle.write(f"server demo-{slot}:8000;\n")
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def subprocess_bounded(args: list[str], timeout: int = DOCKER_TIMEOUT_SECONDS) -> str:
    # A new session ensures cleanup cannot signal the caller's terminal group.
    process = subprocess.Popen(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=2)
        raise RouteError(f"Timed out after {timeout}s: {' '.join(args[:3])}") from exc
    if process.returncode:
        raise RouteError(
            f"Command failed ({process.returncode}): {' '.join(args[:3])}; "
            f"output={stdout[-900:].strip()}"
        )
    return stdout.strip()


def nginx_container_id() -> str:
    cid = subprocess_bounded(
        ["sudo", "-n", "docker", "compose", "ps", "-q", "nginx"]
    ).strip()
    if not cid or "\n" in cid:
        raise RouteError("Expected one existing Nginx container")
    owner = subprocess_bounded(
        [
            "sudo",
            "-n",
            "docker",
            "inspect",
            "--format",
            '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}',
            cid,
        ]
    )
    service = subprocess_bounded(
        [
            "sudo",
            "-n",
            "docker",
            "inspect",
            "--format",
            '{{ index .Config.Labels "com.docker.compose.service" }}',
            cid,
        ]
    )
    if owner != str(ROOT) or service != "nginx":
        raise RouteError("Nginx container belongs to a different checkout/service")
    return cid


def nginx_exec(cid: str, *arguments: str) -> None:
    # Use direct `docker exec`, not `docker compose exec` (observed to hang).
    # sudo -n fails fast rather than waiting for a hidden password prompt.
    output = subprocess_bounded(
        ["sudo", "-n", "docker", "exec", cid, "nginx", *arguments]
    )
    if output:
        print(output, flush=True)


def wait_for_live(expected: tuple[str, str], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = release(LIVE_PORT)
            if last == expected:
                return
        except (OSError, ValueError, RouteError, http.client.HTTPException) as exc:
            last = str(exc)
        time.sleep(0.25)
    raise RouteError(f"Nginx did not converge: expected={expected}; actual={last}")


def check_locked(handle) -> tuple[str, tuple[str, str]]:
    configured = read_route(handle)
    observed, identity = observed_live_slot()
    if configured != observed:
        raise RouteError(
            f"Disk route={configured}, live traffic={observed}. "
            "Run `python3 scripts/nginx_route.py reconcile` before any deploy."
        )
    return configured, identity


def route_command(action: str, target: str | None = None) -> None:
    if ROUTE.is_symlink() or not ROUTE.is_file():
        raise RouteError("Expected a regular, non-symlink Nginx routing file")
    if not stat.S_ISREG(ROUTE.stat().st_mode):
        raise RouteError("Unexpected routing file type")

    with ROUTE.open("r+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RouteError("Another Nginx routing operation is active") from exc

        if action == "check":
            slot, identity = check_locked(handle)
            print(f"PASS: configured/live={slot}, release={identity[0]}")
            return

        if action == "validate":
            slot, _identity = check_locked(handle)
            cid = nginx_container_id()
            nginx_exec(cid, "-t")
            print(f"PASS: direct Docker Nginx validation succeeded for {slot}")
            return

        if action == "reconcile":
            configured = read_route(handle)
            actual, identity = observed_live_slot()
            if configured != actual:
                write_route(handle, actual)
                # Do not reload: running Nginx already serves this proven slot.
                if observed_live_slot()[0] != actual:
                    raise RouteError("Live traffic changed during reconciliation")
                print(f"PASS: restored disk route to live {actual}")
            else:
                print(f"PASS: disk route already matches live {actual}")
            print(f"PASS: live release={identity[0]}; Nginx NOT reloaded")
            return

        if action != "switch" or target not in PORTS:
            raise RouteError("Unknown action/target")
        original, original_release = check_locked(handle)
        if target == original:
            raise RouteError("Target is already the production slot")
        if get_json(PORTS[target], "/ready").get("status") != "ready":
            raise RouteError("Candidate readiness returned an unexpected status")
        candidate_release = release(PORTS[target])
        if candidate_release == original_release:
            raise RouteError("Candidate and production identities are identical")

        cid = nginx_container_id()

        def on_terminate(_signum, _frame):
            raise RouteError("Interrupted during traffic switch")

        previous_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, on_terminate)
        try:
            write_route(handle, target)
            emit_step("running", "Nginx configuration validated")
            nginx_exec(cid, "-t")
            emit_step("success", "Nginx configuration validated")
            emit_step("running", "Traffic switched")
            nginx_exec(cid, "-s", "reload")
            wait_for_live(candidate_release)
            emit_step("success", "Traffic switched")
            print(f"PASS: production switched {original} -> {target}")
            return
        except (Exception, KeyboardInterrupt) as exc:
            # Ignore repeated SIGTERM only while restoring original production.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            print(f"ERROR: switch failed: {exc}; restoring {original}", flush=True)
            write_route(handle, original)
            try:
                nginx_exec(cid, "-t")
                nginx_exec(cid, "-s", "reload")
                wait_for_live(original_release)
                print(f"PASS: original production restored ({original})", flush=True)
            except Exception as restore_exc:
                print(
                    f"CRITICAL: could not confirm original production: {restore_exc}. "
                    "STOP; inspect Nginx before another deploy.",
                    file=sys.stderr,
                    flush=True,
                )
            emit_step("failed", "Traffic switched")
            raise RouteError(f"Traffic switch aborted: {exc}") from exc
        finally:
            signal.signal(signal.SIGTERM, previous_handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "reconcile", "validate", "switch"))
    parser.add_argument("target", nargs="?", choices=("blue", "green"))
    options = parser.parse_args()
    if (options.action == "switch") != (options.target is not None):
        parser.error("Target slot is required only for switch")
    try:
        route_command(options.action, options.target)
    except (RouteError, OSError, ValueError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
