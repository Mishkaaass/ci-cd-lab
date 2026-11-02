from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from opsboard.models import (
    DeploymentOperation,
    OperationStep,
)
from opsboard.operation_lock import DeploymentOperationLock

ACTIVE_OPERATION_STATUSES = {
    "queued",
    "running",
}

OPERATION_LOCK_NAME = "deployment"

DEPLOYMENT_STEP_NAMES = [
    "Candidate selected",
    "Container started",
    "Readiness check",
    "Release identity verified",
    "Nginx configuration validated",
    "Traffic switched",
    "Production converged",
]

ROLLBACK_STEP_NAMES = [
    "Rollback target selected",
    "Target readiness verified",
    "Traffic switched",
    "Production converged",
]


def acquire_operation_lock(
    db: Session,
) -> bool:
    lock = DeploymentOperationLock(
        name=OPERATION_LOCK_NAME,
    )

    db.add(lock)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False

    return True


def release_operation_lock(
    db: Session,
) -> None:
    statement = delete(DeploymentOperationLock).where(
        DeploymentOperationLock.name == OPERATION_LOCK_NAME
    )

    db.execute(statement)
    db.commit()


def create_operation(
    db: Session,
    *,
    action: str,
    step_names: list[str],
    slot: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
) -> DeploymentOperation:
    operation = DeploymentOperation(
        action=action,
        status="queued",
        slot=slot,
        version=version,
        git_sha=git_sha,
    )

    operation.steps = [
        OperationStep(
            position=position,
            name=step_name,
            status="pending",
        )
        for position, step_name in enumerate(
            step_names,
            start=1,
        )
    ]

    db.add(operation)
    db.commit()
    db.refresh(operation)

    return operation


def get_active_operation(
    db: Session,
) -> DeploymentOperation | None:
    statement = (
        select(DeploymentOperation)
        .where(
            DeploymentOperation.status.in_(
                ACTIVE_OPERATION_STATUSES,
            )
        )
        .order_by(
            DeploymentOperation.id.desc(),
        )
        .limit(1)
    )

    return db.scalar(statement)


def queue_operation(
    db: Session,
    *,
    action: str,
    slot: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
) -> DeploymentOperation | None:
    if get_active_operation(db) is not None:
        return None

    if not acquire_operation_lock(db):
        return None

    if action == "rollback":
        step_names = ROLLBACK_STEP_NAMES
    else:
        step_names = DEPLOYMENT_STEP_NAMES

    try:
        return create_operation(
            db,
            action=action,
            step_names=step_names,
            slot=slot,
            version=version,
            git_sha=git_sha,
        )
    except Exception:
        db.rollback()
        release_operation_lock(db)
        raise


def get_operation(
    db: Session,
    operation_id: int,
) -> DeploymentOperation | None:
    statement = (
        select(DeploymentOperation)
        .options(
            selectinload(
                DeploymentOperation.steps,
            )
        )
        .where(
            DeploymentOperation.id == operation_id,
        )
    )

    return db.scalar(statement)


def list_operations(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[DeploymentOperation]:
    statement = (
        select(DeploymentOperation)
        .options(
            selectinload(
                DeploymentOperation.steps,
            )
        )
        .order_by(
            DeploymentOperation.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )

    return list(db.scalars(statement).all())
