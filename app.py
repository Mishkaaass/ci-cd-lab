import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from opsboard.database import Base, engine, get_db
from opsboard.deployments import (
    create_deployment,
    list_deployments,
)
from opsboard.incidents import (
    create_incident,
    list_incidents,
    resolve_incident,
)
from opsboard.monitor import fetch_demo_service_status
from opsboard.schemas import (
    DeploymentCreate,
    DeploymentRead,
    IncidentCreate,
    IncidentRead,
)

DatabaseSession = Annotated[
    Session,
    Depends(get_db),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="OpsBoard API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
def home():
    return {
        "message": "OpsBoard API",
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def readiness(
    db: DatabaseSession,
):
    try:
        db.execute(text("SELECT 1"))

        return {
            "status": "ready",
            "database": "ok",
        }

    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "unavailable",
            },
        )


@app.get("/version")
def version():
    return {
        "version": os.getenv("APP_VERSION", "dev"),
        "git_sha": os.getenv("GIT_SHA", "local"),
    }


@app.get("/api/services/demo")
def demo_service_status():
    return fetch_demo_service_status()


@app.post(
    "/api/deployments",
    response_model=DeploymentRead,
    status_code=201,
)
def add_deployment(
    payload: DeploymentCreate,
    db: DatabaseSession,
):
    return create_deployment(db, payload)


@app.get(
    "/api/deployments",
    response_model=list[DeploymentRead],
)
def deployments(
    db: DatabaseSession,
):
    return list_deployments(db)


@app.post(
    "/api/incidents",
    response_model=IncidentRead,
    status_code=201,
)
def add_incident(
    payload: IncidentCreate,
    db: DatabaseSession,
):
    return create_incident(db, payload)


@app.get(
    "/api/incidents",
    response_model=list[IncidentRead],
)
def incidents(
    db: DatabaseSession,
):
    return list_incidents(db)


@app.post(
    "/api/incidents/{incident_id}/resolve",
    response_model=IncidentRead,
)
def resolve_existing_incident(
    incident_id: int,
    db: DatabaseSession,
):
    incident = resolve_incident(
        db,
        incident_id,
    )

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return incident
