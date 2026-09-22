import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import opsboard.deployment_runner as deployment_runner
from opsboard.database import Base
from opsboard.operation_executor import execute_operation
from opsboard.operations import create_operation, get_operation


def make_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


def test_runner_reports_step_events_from_script_output(
    tmp_path,
    monkeypatch,
):
    deploy_script = tmp_path / "deploy-progress.sh"

    deploy_script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

echo 'normal deployment output'
echo 'OPSBOARD_STEP|running|Container started'
echo 'OPSBOARD_STEP|success|Container started'
echo 'OPSBOARD_STEP|running|Readiness check'
echo 'OPSBOARD_STEP|failed|Readiness check'

exit 1
"""
    )

    deploy_script.chmod(0o755)

    monkeypatch.setattr(
        deployment_runner,
        "DEPLOY_SCRIPT",
        str(deploy_script),
    )

    events = []

    result = deployment_runner.run_deployment_action(
        action="deploy_broken",
        slot="green",
        version="v-progress",
        git_sha="progress123",
        timeout_seconds=2,
        on_step=lambda name, status: events.append(
            (
                name,
                status,
            )
        ),
    )

    assert result.returncode == 1

    assert events == [
        (
            "Container started",
            "running",
        ),
        (
            "Container started",
            "success",
        ),
        (
            "Readiness check",
            "running",
        ),
        (
            "Readiness check",
            "failed",
        ),
    ]


def test_executor_persists_step_progress_while_runner_is_active():
    Session = make_session_factory()

    with Session() as db:
        operation = create_operation(
            db,
            action="deploy_broken",
            slot="green",
            version="v-progress",
            git_sha="progress123",
            step_names=[
                "Candidate selected",
                "Container started",
                "Readiness check",
                "Traffic switched",
            ],
        )

        operation_id = operation.id

    observed_during_run = []

    def fake_runner(
        *,
        on_step,
        **kwargs,
    ):
        on_step(
            "Candidate selected",
            "success",
        )

        on_step(
            "Container started",
            "success",
        )

        on_step(
            "Readiness check",
            "running",
        )

        with Session() as observer:
            current = get_operation(
                observer,
                operation_id,
            )

            observed_during_run.append([step.status for step in current.steps])

        on_step(
            "Readiness check",
            "failed",
        )

        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="candidate failed readiness",
            stderr="",
        )

    with Session() as db:
        execute_operation(
            db,
            operation_id,
            runner=fake_runner,
        )

    assert observed_during_run == [
        [
            "success",
            "success",
            "running",
            "pending",
        ]
    ]

    with Session() as db:
        result = get_operation(
            db,
            operation_id,
        )

        assert result is not None
        assert result.status == "failed"

        assert [step.status for step in result.steps] == [
            "success",
            "success",
            "failed",
            "pending",
        ]
