import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from opsboard.database import Base
from opsboard.operation_executor import execute_operation
from opsboard.operations import create_operation, get_operation


def make_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    Session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    return Session()


def test_successful_operation_becomes_success():
    with make_session() as db:
        operation = create_operation(
            db,
            action="deploy_healthy",
            slot="green",
            version="v3.0.0",
            git_sha="abc123",
            step_names=[
                "Candidate selected",
                "Container started",
                "Production converged",
            ],
        )

        captured = {}

        def fake_runner(**kwargs):
            captured.update(kwargs)

            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="deployment complete",
                stderr="",
            )

        execute_operation(
            db,
            operation.id,
            runner=fake_runner,
        )

        result = get_operation(
            db,
            operation.id,
        )

        assert result is not None
        assert result.status == "success"
        assert result.started_at is not None
        assert result.finished_at is not None

        assert captured == {
            "action": "deploy_healthy",
            "slot": "green",
            "version": "v3.0.0",
            "git_sha": "abc123",
        }

        assert all(step.status == "success" for step in result.steps)


def test_failed_runner_marks_operation_failed():
    with make_session() as db:
        operation = create_operation(
            db,
            action="deploy_broken",
            slot="green",
            version="v3.0.1",
            git_sha="broken123",
            step_names=[
                "Candidate selected",
                "Readiness check",
                "Traffic switched",
            ],
        )

        def fake_runner(**kwargs):
            return subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="readiness failed",
                stderr="candidate rejected",
            )

        execute_operation(
            db,
            operation.id,
            runner=fake_runner,
        )

        result = get_operation(
            db,
            operation.id,
        )

        assert result is not None
        assert result.status == "failed"
        assert result.started_at is not None
        assert result.finished_at is not None

        assert all(step.status == "pending" for step in result.steps)


def test_runner_exception_marks_operation_failed():
    with make_session() as db:
        operation = create_operation(
            db,
            action="rollback",
            step_names=[
                "Rollback target selected",
                "Production converged",
            ],
        )

        def exploding_runner(**kwargs):
            raise RuntimeError("runner exploded")

        execute_operation(
            db,
            operation.id,
            runner=exploding_runner,
        )

        result = get_operation(
            db,
            operation.id,
        )

        assert result is not None
        assert result.status == "failed"
        assert result.finished_at is not None
