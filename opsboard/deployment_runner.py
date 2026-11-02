import os
import re
import signal
import subprocess
from collections.abc import Callable
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import TextIO

DEPLOY_SCRIPT = "./scripts/deploy.sh"
ROLLBACK_SCRIPT = "./scripts/rollback.sh"

DEFAULT_DEPLOYMENT_TIMEOUT_SECONDS = 300.0

VALID_SLOTS = {
    "blue",
    "green",
}

VALID_ACTIONS = {
    "deploy_healthy",
    "deploy_broken",
    "rollback",
}

VALID_STEP_STATUSES = {
    "running",
    "success",
    "failed",
}

STEP_EVENT_PREFIX = "OPSBOARD_STEP|"

RELEASE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

StepCallback = Callable[[str, str], None]


class DeploymentActionError(ValueError):
    pass


def _validate_release_identifier(
    value: str,
    *,
    field_name: str,
) -> None:
    if not RELEASE_IDENTIFIER_PATTERN.fullmatch(value):
        raise DeploymentActionError(f"Invalid {field_name}")


def build_command(
    *,
    action: str,
    slot: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
) -> list[str]:
    if action not in VALID_ACTIONS:
        raise DeploymentActionError("Unsupported deployment action")

    if action == "rollback":
        return [
            ROLLBACK_SCRIPT,
        ]

    if slot not in VALID_SLOTS:
        raise DeploymentActionError("Invalid deployment slot")

    if version is None:
        raise DeploymentActionError("Version is required")

    if git_sha is None:
        raise DeploymentActionError("Git SHA is required")

    _validate_release_identifier(
        version,
        field_name="version",
    )

    _validate_release_identifier(
        git_sha,
        field_name="Git SHA",
    )

    mode = "healthy" if action == "deploy_healthy" else "broken"

    return [
        DEPLOY_SCRIPT,
        slot,
        version,
        git_sha,
        mode,
    ]


def _timeout_message(
    timeout_seconds: float,
) -> str:
    return f"Deployment command timed out after {timeout_seconds:g} seconds."


def _read_stream(
    stream: TextIO,
    source: str,
    output_queue: Queue,
) -> None:
    try:
        for line in stream:
            output_queue.put(
                (
                    source,
                    line,
                )
            )
    finally:
        output_queue.put(
            (
                source,
                None,
            )
        )


def _parse_step_event(
    line: str,
) -> tuple[str, str] | None:
    clean_line = line.rstrip(
        "\r\n",
    )

    if not clean_line.startswith(
        STEP_EVENT_PREFIX,
    ):
        return None

    parts = clean_line.split(
        "|",
        2,
    )

    if len(parts) != 3:
        return None

    _, status, name = parts

    if status not in VALID_STEP_STATUSES:
        return None

    if not name:
        return None

    return (
        name,
        status,
    )


def _kill_process_group(
    process: subprocess.Popen,
) -> None:
    try:
        os.killpg(
            process.pid,
            signal.SIGKILL,
        )
    except ProcessLookupError:
        pass


def _run_with_timeout(
    command: list[str],
    *,
    timeout_seconds: float | None,
    on_step: StepCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise DeploymentActionError("Timeout must be greater than zero")

    process = subprocess.Popen(
        command,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        process_group=0,
    )

    assert process.stdout is not None
    assert process.stderr is not None

    output_queue = Queue()

    stdout_thread = Thread(
        target=_read_stream,
        args=(
            process.stdout,
            "stdout",
            output_queue,
        ),
        daemon=True,
    )

    stderr_thread = Thread(
        target=_read_stream,
        args=(
            process.stderr,
            "stderr",
            output_queue,
        ),
        daemon=True,
    )

    stdout_thread.start()
    stderr_thread.start()

    stdout_lines = []
    stderr_lines = []

    closed_streams = set()

    deadline = monotonic() + timeout_seconds if timeout_seconds is not None else None

    timed_out = False
    callback_error = None

    while len(closed_streams) < 2:
        if deadline is not None and monotonic() >= deadline and not timed_out:
            timed_out = True
            deadline = None

            _kill_process_group(
                process,
            )

        wait_seconds = 0.05

        if deadline is not None:
            remaining = deadline - monotonic()

            wait_seconds = max(
                0.001,
                min(
                    wait_seconds,
                    remaining,
                ),
            )

        try:
            source, line = output_queue.get(
                timeout=wait_seconds,
            )
        except Empty:
            continue

        if line is None:
            closed_streams.add(
                source,
            )
            continue

        if source == "stdout":
            stdout_lines.append(
                line,
            )

            if on_step is not None and callback_error is None:
                event = _parse_step_event(
                    line,
                )

                if event is not None:
                    name, status = event

                    try:
                        on_step(
                            name,
                            status,
                        )
                    except Exception as exc:
                        callback_error = exc
                        deadline = None

                        _kill_process_group(
                            process,
                        )

        else:
            stderr_lines.append(
                line,
            )

    stdout_thread.join()
    stderr_thread.join()

    process.wait()

    if callback_error is not None:
        raise callback_error

    stdout = "".join(
        stdout_lines,
    )

    stderr = "".join(
        stderr_lines,
    )

    if timed_out:
        message = _timeout_message(
            timeout_seconds,
        )

        if stderr and not stderr.endswith(
            "\n",
        ):
            stderr += "\n"

        stderr += f"{message}\n"

        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=stdout,
            stderr=stderr,
        )

    return subprocess.CompletedProcess(
        args=command,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def run_deployment_action(
    *,
    action: str,
    slot: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
    timeout_seconds: float | None = None,
    on_step: StepCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    command = build_command(
        action=action,
        slot=slot,
        version=version,
        git_sha=git_sha,
    )

    if timeout_seconds is None and on_step is None:
        return subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )

    return _run_with_timeout(
        command,
        timeout_seconds=timeout_seconds,
        on_step=on_step,
    )
