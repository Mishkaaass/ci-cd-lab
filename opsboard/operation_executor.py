from collections.abc import Callable
from datetime import UTC, datetime
from threading import Thread

from sqlalchemy.orm import Session, sessionmaker

from opsboard.database import SessionLocal
from opsboard.deployment_runner import run_deployment_action
from opsboard.operations import get_operation

Runner = Callable[..., object]


def utc_now():
    return datetime.now(UTC)


def execute_operation(
    db: Session,
    operation_id: int,
    *,
    runner: Runner = run_deployment_action,
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

    try:
        result = runner(
            action=operation.action,
            slot=operation.slot,
            version=operation.version,
            git_sha=operation.git_sha,
        )

        if result.returncode == 0:
            operation.status = "success"

            for step in operation.steps:
                step.status = "success"

        else:
            operation.status = "failed"

    except Exception:
        operation.status = "failed"

    operation.finished_at = utc_now()

    db.commit()


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
