"""Offline, deterministic tests of the public first-time reviewer experience."""

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def setup_reviewer(tmp_path, *, bad_changes_live=False, bad_succeeds=False):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/reviewer.sh", repo / "scripts/reviewer.sh")
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"version": "v1.4.1", "git_sha": "good789"}))
    commands = tmp_path / "commands.txt"
    route_helper = repo / "scripts/nginx_route.py"
    route_helper.write_text('print("PASS: configured and live route match")\n')
    helper = repo / "scripts/lab.sh"
    helper.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$RECORDED_COMMANDS"
case "$1 ${2:-}" in
  'deploy broken')
    if [ "$BROKEN_MOVES_TRAFFIC" = 1 ]; then
      printf '%s' '{"version":"bad","git_sha":"bad"}' > "$LIVE_STATE"
    fi
    [ "$BROKEN_SUCCEEDS" = 1 ] && exit 0
    exit 7
    ;;
  'deploy healthy')
    printf '{"version":"%s","git_sha":"%s"}' "$3" "$4" > "$LIVE_STATE"
    ;;
  'rollback ')
    printf '%s' '{"version":"v1.4.1","git_sha":"good789"}' > "$LIVE_STATE"
    ;;
  *) exit 2 ;;
esac
"""
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
case "${*: -1}" in
  */ready) echo '{"status":"ready","database":"ok"}';;
  */version) cat "$LIVE_STATE";;
  *) exit 7;;
esac
"""
    )
    curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "RECORDED_COMMANDS": str(commands),
        "LIVE_STATE": str(live),
        "BROKEN_MOVES_TRAFFIC": "1" if bad_changes_live else "0",
        "BROKEN_SUCCEEDS": "1" if bad_succeeds else "0",
    }
    return repo, env, live, commands


def call_reviewer(repo, env, *args):
    return subprocess.run(
        ["bash", "scripts/reviewer.sh", *args],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )


def test_drill_verifies_broken_healthy_and_exact_rollback(tmp_path):
    repo, env, live, commands = setup_reviewer(tmp_path)
    result = call_reviewer(repo, env, "drill")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "PASS: broken gate, healthy rollout, exact rollback identity" in result.stdout
    )
    assert json.loads(live.read_text()) == {"version": "v1.4.1", "git_sha": "good789"}
    calls = commands.read_text().splitlines()
    assert calls[0].startswith("deploy broken bad-")
    assert calls[1].startswith("deploy healthy good-")
    assert calls[2] == "rollback"


def test_drill_rejects_broken_candidate_that_passed_gate(tmp_path):
    repo, env, _, commands = setup_reviewer(tmp_path, bad_succeeds=True)
    result = call_reviewer(repo, env, "drill")
    assert result.returncode != 0
    assert "unexpectedly succeeded" in result.stderr
    assert len(commands.read_text().splitlines()) == 1


def test_drill_stops_if_broken_release_changes_live_traffic(tmp_path):
    repo, env, live, commands = setup_reviewer(tmp_path, bad_changes_live=True)
    result = call_reviewer(repo, env, "drill")
    assert result.returncode != 0
    assert "changed live traffic" in result.stderr
    assert json.loads(live.read_text())["version"] == "bad"
    assert len(commands.read_text().splitlines()) == 1


def test_help_requires_no_docker_or_network(tmp_path):
    repo, env, _, _ = setup_reviewer(tmp_path)
    result = call_reviewer(repo, env, "help")
    assert result.returncode == 0
    assert "broken" not in result.stderr.lower()
    assert "drill" in result.stdout
