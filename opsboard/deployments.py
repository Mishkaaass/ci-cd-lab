from sqlalchemy import select
from sqlalchemy.orm import Session

from opsboard.models import Deployment
from opsboard.schemas import DeploymentCreate


def create_deployment(
    db: Session,
    payload: DeploymentCreate,
) -> Deployment:
    deployment = Deployment(**payload.model_dump())

    db.add(deployment)
    db.commit()
    db.refresh(deployment)

    return deployment


def list_deployments(db: Session) -> list[Deployment]:
    statement = select(Deployment).order_by(Deployment.id.desc())

    return list(db.scalars(statement))
