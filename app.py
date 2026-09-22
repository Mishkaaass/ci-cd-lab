import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
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
from opsboard.operation_executor import dispatch_operation
from opsboard.operations import (
    get_operation,
    list_operations,
    queue_operation,
)
from opsboard.schemas import (
    DeploymentCreate,
    DeploymentOperationRead,
    DeploymentOperationRequest,
    DeploymentRead,
    IncidentCreate,
    IncidentRead,
)

DatabaseSession = Annotated[
    Session,
    Depends(get_db),
]

OperationDispatcher = Callable[[int], None]


def get_operation_dispatcher() -> OperationDispatcher:
    return dispatch_operation


OperationDispatcherDependency = Annotated[
    OperationDispatcher,
    Depends(get_operation_dispatcher),
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

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)

templates = Jinja2Templates(
    directory="templates",
)


@app.get("/")
def home():
    return {
        "message": "OpsBoard API",
        "status": "running",
    }


@app.get(
    "/dashboard",
    response_class=HTMLResponse,
)
def dashboard(
    request: Request,
    db: DatabaseSession,
):
    service = fetch_demo_service_status()

    deployments = list_deployments(db)[:10]
    incidents = list_incidents(db)[:10]
    operations = list_operations(db)[:10]

    active_incidents = [
        incident for incident in incidents if incident.status == "active"
    ]

    latest_deployment = deployments[0] if deployments else None

    latest_operation = operations[0] if operations else None

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "environment": os.getenv(
                "APP_ENV",
                "local",
            ),
            "service": service,
            "deployments": deployments,
            "latest_deployment": latest_deployment,
            "incidents": incidents,
            "active_incidents": active_incidents,
            "operations": operations,
            "latest_operation": latest_operation,
        },
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
    }


@app.get("/ready")
def readiness(
    db: DatabaseSession,
):
    try:
        db.execute(
            text("SELECT 1"),
        )

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
        "version": os.getenv(
            "APP_VERSION",
            "dev",
        ),
        "git_sha": os.getenv(
            "GIT_SHA",
            "local",
        ),
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
    return create_deployment(
        db,
        payload,
    )


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
    return create_incident(
        db,
        payload,
    )


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


def queue_or_conflict(
    db: Session,
    *,
    action: str,
    slot: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
):
    operation = queue_operation(
        db,
        action=action,
        slot=slot,
        version=version,
        git_sha=git_sha,
    )

    if operation is None:
        raise HTTPException(
            status_code=409,
            detail=("Another deployment operation is already active"),
        )

    return operation


def schedule_operation(
    background_tasks: BackgroundTasks,
    dispatcher: OperationDispatcher,
    operation_id: int,
) -> None:
    background_tasks.add_task(
        dispatcher,
        operation_id,
    )


@app.post(
    "/api/operations/deploy-healthy",
    response_model=DeploymentOperationRead,
    status_code=202,
)
def deploy_healthy(
    payload: DeploymentOperationRequest,
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    dispatcher: OperationDispatcherDependency,
):
    operation = queue_or_conflict(
        db,
        action="deploy_healthy",
        slot=payload.slot,
        version=payload.version,
        git_sha=payload.git_sha,
    )

    schedule_operation(
        background_tasks,
        dispatcher,
        operation.id,
    )

    return operation


@app.post(
    "/api/operations/deploy-broken",
    response_model=DeploymentOperationRead,
    status_code=202,
)
def deploy_broken(
    payload: DeploymentOperationRequest,
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    dispatcher: OperationDispatcherDependency,
):
    operation = queue_or_conflict(
        db,
        action="deploy_broken",
        slot=payload.slot,
        version=payload.version,
        git_sha=payload.git_sha,
    )

    schedule_operation(
        background_tasks,
        dispatcher,
        operation.id,
    )

    return operation


@app.post(
    "/api/operations/rollback",
    response_model=DeploymentOperationRead,
    status_code=202,
)
def rollback(
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    dispatcher: OperationDispatcherDependency,
):
    operation = queue_or_conflict(
        db,
        action="rollback",
    )

    schedule_operation(
        background_tasks,
        dispatcher,
        operation.id,
    )

    return operation


@app.get(
    "/api/operations",
    response_model=list[DeploymentOperationRead],
)
def operations(
    db: DatabaseSession,
):
    return list_operations(db)


@app.get(
    "/api/operations/{operation_id}",
    response_model=DeploymentOperationRead,
)
def operation(
    operation_id: int,
    db: DatabaseSession,
):
    result = get_operation(
        db,
        operation_id,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Operation not found",
        )

    return result
