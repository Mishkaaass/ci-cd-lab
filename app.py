import base64
import hashlib
import os
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
)
from fastapi import (
    Path as ApiPath,
)
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
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
from opsboard.models import Incident
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
from opsboard.security import (
    CSP,
    SECURITY_HEADERS,
    RequestLimiter,
    SecurityMiddleware,
    authentication_ready,
    deployments_enabled,
    require_actor,
)

DatabaseSession = Annotated[
    Session,
    Depends(get_db),
]

OperationDispatcher = Callable[[int], None]

NGINX_ACTIVE_BACKEND_CONFIG = Path("nginx/active_backend.inc")

ACTIVE_BACKEND_PATTERN = re.compile(
    r"^\s*server demo-(blue|green):8000;\s*$",
    re.MULTILINE,
)


def get_operation_dispatcher() -> OperationDispatcher:
    return dispatch_operation


OperationDispatcherDependency = Annotated[
    OperationDispatcher,
    Depends(get_operation_dispatcher),
]


def resolve_inactive_slot(
    config_path: str | Path = NGINX_ACTIVE_BACKEND_CONFIG,
) -> str:
    content = Path(
        config_path,
    ).read_text()

    matches = ACTIVE_BACKEND_PATTERN.findall(
        content,
    )

    if len(matches) != 1:
        raise ValueError("Unable to determine active production slot")

    active_slot = matches[0]

    if active_slot == "blue":
        return "green"

    return "blue"


def deployment_target_slot() -> str:
    try:
        return resolve_inactive_slot()
    except (
        OSError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=("Unable to determine active production slot"),
        ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(
        bind=engine,
    )

    yield


app = FastAPI(
    title="OpsBoard API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.state.request_limiter = RequestLimiter()
app.add_middleware(SecurityMiddleware, limiter=app.state.request_limiter)
api = APIRouter(prefix="/api", dependencies=[Depends(require_actor)])


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                for error in exc.errors()
            ]
        },
    )


@app.exception_handler(Exception)
async def unexpected_error(request, _exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={
            **SECURITY_HEADERS,
            "X-Request-ID": getattr(request.state, "request_id", ""),
        },
    )


@app.get("/docs", include_in_schema=False)
def api_documentation():
    response = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="OpsBoard API",
        swagger_ui_parameters={"persistAuthorization": False},
    )
    scripts = re.findall(r"<script>(.*?)</script>", response.body.decode(), re.S)
    hashes = " ".join(
        "'sha256-"
        + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        + "'"
        for script in scripts
    )
    response.headers["Content-Security-Policy"] = (
        CSP.replace(
            "script-src 'self'", f"script-src 'self' https://cdn.jsdelivr.net {hashes}"
        )
        .replace("style-src 'self'", "style-src 'self' https://cdn.jsdelivr.net")
        .replace(
            "img-src 'self' data:", "img-src 'self' data: https://fastapi.tiangolo.com"
        )
    )
    return response


app.mount(
    "/static",
    StaticFiles(
        directory="static",
    ),
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
):
    # Navigation never embeds operational data. The browser reads protected APIs.
    service = {
        "name": "demo-api",
        "status": "unknown",
        "ready": False,
        "latency_ms": None,
        "version": "—",
        "git_sha": "—",
    }
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "environment": os.getenv(
                "APP_ENV",
                "local",
            ),
            "service": service,
            "deployments": [],
            "latest_deployment": None,
            "incidents": [],
            "active_incidents": [],
            "operations": [],
            "latest_operation": None,
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
    if not authentication_ready():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "authentication": "unavailable"},
        )
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


@api.get("/services/demo")
def demo_service_status():
    return fetch_demo_service_status()


@api.post(
    "/deployments",
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


@api.get(
    "/deployments",
    response_model=list[DeploymentRead],
)
def deployments(
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
):
    return list_deployments(db, limit=limit, offset=offset)


@api.post(
    "/incidents",
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


@api.get(
    "/incidents",
    response_model=list[IncidentRead],
)
def incidents(
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
):
    return list_incidents(db, limit=limit, offset=offset)


@api.post(
    "/incidents/{incident_id}/resolve",
    response_model=IncidentRead,
)
def resolve_existing_incident(
    incident_id: Annotated[int, ApiPath(ge=1, le=2**31 - 1)],
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


@api.post(
    "/operations/deploy-healthy",
    response_model=DeploymentOperationRead,
    status_code=202,
)
def deploy_healthy(
    payload: DeploymentOperationRequest,
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    dispatcher: OperationDispatcherDependency,
):
    slot = deployment_target_slot()

    operation = queue_or_conflict(
        db,
        action="deploy_healthy",
        slot=slot,
        version=payload.version,
        git_sha=payload.git_sha,
    )

    schedule_operation(
        background_tasks,
        dispatcher,
        operation.id,
    )

    return operation


@api.post(
    "/operations/deploy-broken",
    response_model=DeploymentOperationRead,
    status_code=202,
)
def deploy_broken(
    payload: DeploymentOperationRequest,
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    dispatcher: OperationDispatcherDependency,
):
    slot = deployment_target_slot()

    operation = queue_or_conflict(
        db,
        action="deploy_broken",
        slot=slot,
        version=payload.version,
        git_sha=payload.git_sha,
    )

    schedule_operation(
        background_tasks,
        dispatcher,
        operation.id,
    )

    return operation


@api.post(
    "/operations/rollback",
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


@api.get(
    "/operations",
    response_model=list[DeploymentOperationRead],
)
def operations(
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
):
    return list_operations(db, limit=limit, offset=offset)


@api.get(
    "/operations/{operation_id}",
    response_model=DeploymentOperationRead,
)
def operation(
    operation_id: Annotated[int, ApiPath(ge=1, le=2**31 - 1)],
    db: DatabaseSession,
):
    result = get_operation(
        db,
        operation_id,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=("Operation not found"),
        )

    return result


@api.get("/auth/me")
def actor_identity(request: Request):
    actor = request.state.actor
    return {
        "name": actor.name,
        "role": actor.role,
        "can_write": actor.role == "operator",
        "deployment_actions_enabled": actor.role == "operator"
        and deployments_enabled(),
        "expires_at": actor.expires_at,
    }


@api.get("/dashboard")
def dashboard_data(db: DatabaseSession):
    return {
        "service": fetch_demo_service_status(),
        "deployments": [
            DeploymentRead.model_validate(item)
            for item in list_deployments(db, limit=10)
        ],
        "incidents": [
            IncidentRead.model_validate(item) for item in list_incidents(db, limit=10)
        ],
        "operations": [
            DeploymentOperationRead.model_validate(item)
            for item in list_operations(db, limit=10)
        ],
        "active_incident_count": db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.status == "active")
        ),
    }


app.include_router(api)
