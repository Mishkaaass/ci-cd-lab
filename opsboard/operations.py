from sqlalchemy.orm import Session

from opsboard.models import DeploymentOperation, OperationStep


def create_operation(
    db: Session,
    *,
    action: str,
    step_names: list[str],
) -> DeploymentOperation:
    operation = DeploymentOperation(
        action=action,
        status="queued",
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
