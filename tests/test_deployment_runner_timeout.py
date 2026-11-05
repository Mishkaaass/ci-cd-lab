import os
import time
from pathlib import Path

import opsboard.deployment_runner as deployment_runner


def process_is_alive(pid: int) -> bool:
    stat_file = Path(f"/proc/{pid}/stat")

    if not stat_file.exists():
        return False

    try:
        state = stat_file.read_text().split()[2]
    except FileNotFoundError, ProcessLookupError, IndexError:
        return False

    return state != "Z"


def test_runner_times_out_and_kills_process_group(
    tmp_path,
    monkeypatch,
):
    pid_file = tmp_path / "child.pid"
    deploy_script = tmp_path / "deploy-timeout.sh"

    deploy_script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

sleep 30 &
child=$!

printf '%s\\n' "$child" > "{pid_file}"

wait "$child"
"""
    )

    deploy_script.chmod(0o755)

    monkeypatch.setattr(
        deployment_runner,
        "DEPLOY_SCRIPT",
        str(deploy_script),
    )

    started_at = time.monotonic()

    result = deployment_runner.run_deployment_action(
        action="deploy_healthy",
        slot="green",
        version="v-timeout",
        git_sha="timeout123",
        timeout_seconds=0.2,
    )

    elapsed = time.monotonic() - started_at

    assert result.returncode == 124
    assert elapsed < 2
    assert "timed out" in result.stderr.lower()

    child_pid = int(pid_file.read_text().strip())

    for _ in range(20):
        if not process_is_alive(child_pid):
            break

        time.sleep(0.05)

    assert not process_is_alive(child_pid)


def test_runner_uses_own_process_group_without_new_session(
    tmp_path,
    monkeypatch,
):
    process_file = tmp_path / "process-info.txt"
    deploy_script = tmp_path / "deploy-process-group.sh"

    deploy_script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

python3 - "{process_file}" <<'PYTHON'
import os
import sys
with open(sys.argv[1], "w") as handle:
    print(os.getsid(0), os.getpgrp(), file=handle)
PYTHON
"""
    )

    deploy_script.chmod(0o755)

    monkeypatch.setattr(
        deployment_runner,
        "DEPLOY_SCRIPT",
        str(deploy_script),
    )

    parent_sid = os.getsid(0)
    parent_pgid = os.getpgrp()

    result = deployment_runner.run_deployment_action(
        action="deploy_healthy",
        slot="green",
        version="v-process-group",
        git_sha="group123",
        timeout_seconds=2,
    )

    child_sid, child_pgid = (int(value) for value in process_file.read_text().split())

    assert result.returncode == 0

    assert child_sid == parent_sid
    assert child_pgid != parent_pgid
