import os
import re
import signal
import subprocess

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

RELEASE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


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


def _run_with_timeout(
    command: list[str],
    *,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise DeploymentActionError("Timeout must be greater than zero")

    process = subprocess.Popen(
        command,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        process_group=0,
    )

    try:
        stdout, stderr = process.communicate(
            timeout=timeout_seconds,
        )

        return subprocess.CompletedProcess(
            args=command,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    except subprocess.TimeoutExpired:
        try:
            os.killpg(
                process.pid,
                signal.SIGKILL,
            )
        except ProcessLookupError:
            pass

        stdout, stderr = process.communicate()

        message = _timeout_message(timeout_seconds)

        stderr = stderr or ""

        if stderr and not stderr.endswith("\n"):
            stderr += "\n"

        stderr += f"{message}\n"

        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=stdout or "",
            stderr=stderr,
        )


def run_deployment_action(
    *,
    action: str,
    slot: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    command = build_command(
        action=action,
        slot=slot,
        version=version,
        git_sha=git_sha,
    )

    if timeout_seconds is None:
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
    )
