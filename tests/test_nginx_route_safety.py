"""Offline safety tests: no Docker, network, or root access required."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "nginx_route.py"
spec = importlib.util.spec_from_file_location("nginx_route", SCRIPT)
assert spec and spec.loader
nginx_route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nginx_route)


@pytest.fixture
def mock_lab(tmp_path, monkeypatch):
    route = tmp_path / "active_backend.inc"
    route.write_text("server demo-green:8000;\n")
    monkeypatch.setattr(nginx_route, "ROOT", tmp_path)
    monkeypatch.setattr(nginx_route, "ROUTE", route)
    state = {"live": "green", "validation_failure": False, "exec_calls": []}
    identities = {"blue": ("v2", "sha2"), "green": ("v1", "sha1")}

    def observed():
        slot = state["live"]
        return slot, identities[slot]

    def get_json(port, path="/version"):
        assert path == "/ready"
        assert port in nginx_route.PORTS.values()
        return {"status": "ready"}

    def release(port):
        for slot, assigned in nginx_route.PORTS.items():
            if port == assigned:
                return identities[slot]
        if port == 8080:
            return identities[state["live"]]
        raise AssertionError("Unexpected port")

    def nginx_exec(_cid, *arguments):
        state["exec_calls"].append(arguments)
        if arguments == ("-t",) and state["validation_failure"]:
            state["validation_failure"] = False
            raise nginx_route.RouteError("simulated config failure")
        if arguments == ("-s", "reload"):
            state["live"] = route.read_text().split("demo-")[1].split(":")[0]

    monkeypatch.setattr(nginx_route, "observed_live_slot", observed)
    monkeypatch.setattr(nginx_route, "get_json", get_json)
    monkeypatch.setattr(nginx_route, "release", release)
    monkeypatch.setattr(nginx_route, "nginx_container_id", lambda: "nginx-test-cid")
    monkeypatch.setattr(nginx_route, "nginx_exec", nginx_exec)
    monkeypatch.setattr(
        nginx_route,
        "wait_for_live",
        lambda expected: (
            None
            if identities[state["live"]] == expected
            else (_ for _ in ()).throw(nginx_route.RouteError("wrong release"))
        ),
    )
    return route, state


def test_detect_stale_host_route_without_writes(mock_lab):
    route, _ = mock_lab
    route.write_text("server demo-blue:8000;\n")
    with pytest.raises(nginx_route.RouteError, match="Disk route=blue"):
        nginx_route.route_command("check")
    assert route.read_text() == "server demo-blue:8000;\n"


def test_reconcile_to_proven_live_route_without_reload(mock_lab):
    route, state = mock_lab
    route.write_text("server demo-blue:8000;\n")
    inode = route.stat().st_ino
    nginx_route.route_command("reconcile")
    assert route.read_text() == "server demo-green:8000;\n"
    assert route.stat().st_ino == inode
    assert state["exec_calls"] == []


def test_successful_switch_preserves_bind_mount_inode(mock_lab):
    route, state = mock_lab
    inode = route.stat().st_ino
    nginx_route.route_command("switch", "blue")
    assert route.stat().st_ino == inode
    assert state["live"] == "blue"
    assert route.read_text() == "server demo-blue:8000;\n"
    assert state["exec_calls"] == [("-t",), ("-s", "reload")]


def test_failed_nginx_validation_restores_original_route(mock_lab):
    route, state = mock_lab
    state["validation_failure"] = True
    with pytest.raises(nginx_route.RouteError, match="Traffic switch aborted"):
        nginx_route.route_command("switch", "blue")
    assert state["live"] == "green"
    assert route.read_text() == "server demo-green:8000;\n"
    assert state["exec_calls"] == [("-t",), ("-t",), ("-s", "reload")]


def test_invalid_route_file_is_rejected(mock_lab):
    route, _ = mock_lab
    route.write_text("server untrusted:80;\n")
    with pytest.raises(nginx_route.RouteError, match="Unexpected"):
        nginx_route.route_command("reconcile")


def test_unchanged_route_stays_read_only(mock_lab):
    route, state = mock_lab
    nginx_route.route_command("check")
    assert route.read_text() == "server demo-green:8000;\n"
    assert state["exec_calls"] == []


def test_docker_wrapper_has_hard_timeout():
    with pytest.raises(nginx_route.RouteError, match="Timed out"):
        nginx_route.subprocess_bounded(
            [sys.executable, "-c", "import time; time.sleep(10)"], timeout=1
        )


def test_cli_shell_scripts_never_use_unbounded_compose_exec():
    for name in ("deploy.sh", "rollback.sh"):
        contents = (SCRIPT.parent / name).read_text()
        assert "docker compose exec" not in contents
        assert 'python3 scripts/nginx_route.py switch "$TARGET"' in contents
        assert "python3 scripts/nginx_route.py check" in contents


def test_validate_uses_bounded_read_only_nginx_test(mock_lab):
    route, state = mock_lab
    nginx_route.route_command("validate")
    assert route.read_text() == "server demo-green:8000;\n"
    assert state["exec_calls"] == [("-t",)]


def test_bounded_subprocess_preserves_sudo_tty_session():
    output = nginx_route.subprocess_bounded(
        [
            sys.executable,
            "-c",
            (
                "import os; "
                "print(int(os.getsid(0) == os.getsid(os.getppid()))); "
                "print(int(os.getpgrp() != os.getpgid(os.getppid())))"
            ),
        ],
        timeout=4,
    )
    assert output.splitlines() == ["1", "1"]
