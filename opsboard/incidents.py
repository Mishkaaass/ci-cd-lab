from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from opsboard.models import Incident
from opsboard.schemas import IncidentCreate


def create_incident(
    db: Session,
    payload: IncidentCreate,
) -> Incident:
    incident = Incident(
        **payload.model_dump(),
        status="active",
    )

    db.add(incident)
    db.commit()
    db.refresh(incident)

    return incident


def list_incidents(db: Session) -> list[Incident]:
    statement = select(Incident).order_by(Incident.id.desc())

    return list(db.scalars(statement))


def resolve_incident(
    db: Session,
    incident_id: int,
) -> Incident | None:
    incident = db.get(Incident, incident_id)

    if incident is None:
        return None

    if incident.status != "resolved":
        incident.status = "resolved"
        incident.resolved_at = datetime.now(UTC)

        db.commit()
        db.refresh(incident)

    return incident
