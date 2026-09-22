import subprocess

import pytest

from opsboard.deployment_runner import (
    DeploymentActionError,
    build_command,
    run_deployment_action,
)


def test_build_command_for_healthy_deployment():
    command = build_command(
        action="deploy_healthy",
        slot="green",
        version="v2.0.0",
        git_sha="abc123",
    )

    assert command == [
        "./scripts/deploy.sh",
        "green",
        "v2.0.0",
        "abc123",
        "healthy",
    ]


def test_build_command_for_broken_deployment():
    command = build_command(
        action="deploy_broken",
        slot="blue",
        version="v2.0.1",
        git_sha="def456",
    )

    assert command == [
        "./scripts/deploy.sh",
        "blue",
        "v2.0.1",
        "def456",
        "broken",
    ]


def test_build_command_for_rollback():
    command = build_command(
        action="rollback",
    )

    assert command == [
        "./scripts/rollback.sh",
    ]


def test_unknown_action_is_rejected():
    with pytest.raises(
        DeploymentActionError,
        match="Unsupported deployment action",
    ):
        build_command(
            action="delete_everything",
        )


def test_invalid_slot_is_rejected():
    with pytest.raises(
        DeploymentActionError,
        match="Invalid deployment slot",
    ):
        build_command(
            action="deploy_healthy",
            slot="production",
            version="v2.0.0",
            git_sha="abc123",
        )


def test_invalid_release_identifier_is_rejected():
    with pytest.raises(
        DeploymentActionError,
        match="Invalid version",
    ):
        build_command(
            action="deploy_healthy",
            slot="green",
            version="v2.0.0; rm -rf /",
            git_sha="abc123",
        )


def test_runner_executes_argument_list_without_shell(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="deployment complete",
            stderr="",
        )

    monkeypatch.setattr(
        subprocess,
        "run",
        fake_run,
    )

    result = run_deployment_action(
        action="deploy_healthy",
        slot="green",
        version="v2.0.0",
        git_sha="abc123",
    )

    assert captured["command"] == [
        "./scripts/deploy.sh",
        "green",
        "v2.0.0",
        "abc123",
        "healthy",
    ]

    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True

    assert result.returncode == 0
    assert result.stdout == "deployment complete"
