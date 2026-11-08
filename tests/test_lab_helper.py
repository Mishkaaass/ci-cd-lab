"""Isolation/ownership tests for the safe local terminal launcher.

These never invoke Docker. A fake sudo command records what would have run.
"""

import os
import shutil
import subprocess
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "scripts/lab.sh"


def run_lab(tmp_path, action, *, checkout_owner):
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "nginx").mkdir()
    shutil.copy2(SOURCE, root / "scripts/lab.sh")
    (root / "nginx/active_backend.inc").write_text("server demo-blue:8000;\n")
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    log = tmp_path / "calls.log"
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_CALLS"
case "$*" in
  *'docker info'*) exit 0;;
  *'docker compose config --quiet'*) exit 0;;
  *'docker ps --no-trunc -q --filter publish='*) echo 'container-complete-id'; exit 0;;
  *'docker compose ps --all --no-trunc -q '*) echo 'container-complete-id'; exit 0;;
  *'docker compose ps --no-trunc -q '*) echo 'container-complete-id'; exit 0;;
  *'docker inspect --format '*) printf '%s\\n' "$FAKE_OWNER_ROOT"; exit 0;;
  *'docker compose up '*) exit 0;;
  *'docker compose ps'*) exit 0;;
esac
exit 1
"""
    )
    fake_sudo.chmod(0o755)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/bin/sh
case "$*" in
  */version*) echo '{"version":"v1","git_sha":"test","mode":"healthy"}';;
  *) echo '{"status":"ready"}';;
esac
"""
    )
    fake_curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
        "FAKE_OWNER_ROOT": (
            str(root) if checkout_owner == "same" else str(tmp_path / "other")
        ),
        "FAKE_CALLS": str(log),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    result = subprocess.run(
        ["bash", str(root / "scripts/lab.sh"), *action],
        cwd=root, env=env, text=True, capture_output=True, timeout=12,
    )
    return result, log.read_text() if log.exists() else ""


def test_demo_accepts_same_checkout_full_docker_ids(tmp_path):
    result, calls = run_lab(tmp_path, ["demo"], checkout_owner="same")
    assert result.returncode == 0, result.stderr
    assert "READY:" in result.stdout
    assert "--no-trunc" in calls
    assert "docker compose up" in calls


def test_demo_refuses_other_checkout_before_mutation(tmp_path):
    result, calls = run_lab(tmp_path, ["demo"], checkout_owner="other")
    assert result.returncode != 0
    assert "belongs to" in result.stderr and "use one checkout" in result.stderr.lower()
    assert "docker compose up" not in calls


def test_deploy_refuses_other_checkout_before_running_script(tmp_path):
    result, calls = run_lab(
        tmp_path, ["deploy", "healthy", "v2", "abc123"], checkout_owner="other"
    )
    assert result.returncode != 0
    assert "another checkout" in result.stderr
    assert "docker compose up" not in calls


def test_rollback_refuses_other_checkout_before_running_script(tmp_path):
    result, calls = run_lab(tmp_path, ["rollback"], checkout_owner="other")
    assert result.returncode != 0
    assert "another checkout" in result.stderr
    assert "docker compose up" not in calls
