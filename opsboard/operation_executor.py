import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from threading import Thread

from sqlalchemy.orm import Session, sessionmaker

from opsboard.database import SessionLocal
from opsboard.deployment_runner import (
    DEFAULT_DEPLOYMENT_TIMEOUT_SECONDS,
    run_deployment_action,
)
from opsboard.operations import (
    get_operation,
    release_operation_lock,
)

Runner = Callable[..., object]

VALID_STEP_STATUSES = {
    "running",
    "success",
    "failed",
}

DEFAULT_OPERATION_RUNNER = partial(
    run_deployment_action,
    timeout_seconds=(DEFAULT_DEPLOYMENT_TIMEOUT_SECONDS),
)


def utc_now():
    return datetime.now(UTC)


def _runner_supports_progress(
    runner: Runner,
) -> bool:
    try:
        parameters = inspect.signature(
            runner,
        ).parameters
    except (
        TypeError,
        ValueError,
    ):
        return False

    return "on_step" in parameters


def execute_operation(
    db: Session,
    operation_id: int,
    *,
    runner: Runner = DEFAULT_OPERATION_RUNNER,
) -> None:
    operation = get_operation(
        db,
        operation_id,
    )

    if operation is None:
        return

    operation.status = "running"
    operation.started_at = utc_now()

    db.commit()

    progress_reported = False

    def report_step(
        name: str,
        status: str,
    ) -> None:
        nonlocal progress_reported

        if status not in VALID_STEP_STATUSES:
            return

        for step in operation.steps:
            if step.name != name:
                continue

            step.status = status
            progress_reported = True

            db.commit()

            return

    runner_kwargs = {
        "action": operation.action,
        "slot": operation.slot,
        "version": operation.version,
        "git_sha": operation.git_sha,
    }

    if _runner_supports_progress(
        runner,
    ):
        runner_kwargs["on_step"] = report_step

    try:
        result = runner(
            **runner_kwargs,
        )

        if result.returncode == 0:
            operation.status = "success"

            if not progress_reported:
                for step in operation.steps:
                    step.status = "success"

        else:
            operation.status = "failed"

            for step in operation.steps:
                if step.status == "running":
                    step.status = "failed"

    except Exception:
        operation.status = "failed"

        for step in operation.steps:
            if step.status == "running":
                step.status = "failed"

    operation.finished_at = utc_now()

    release_operation_lock(
        db,
    )


def execute_operation_by_id(
    operation_id: int,
    *,
    session_factory: sessionmaker = SessionLocal,
) -> None:
    with session_factory() as db:
        execute_operation(
            db,
            operation_id,
        )


def dispatch_operation(
    operation_id: int,
) -> None:
    thread = Thread(
        target=execute_operation_by_id,
        args=(operation_id,),
        daemon=True,
        name=f"opsboard-operation-{operation_id}",
    )

    thread.start()
