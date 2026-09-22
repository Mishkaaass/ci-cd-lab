from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DeploymentCreate(BaseModel):
    version: str
    git_sha: str
    image: str
    status: Literal[
        "deploying",
        "success",
        "failed",
        "rolled_back",
    ]
    duration_ms: int | None = Field(
        default=None,
        ge=0,
    )


class DeploymentRead(DeploymentCreate):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: int
    created_at: datetime


class IncidentCreate(BaseModel):
    service: str

    severity: Literal[
        "info",
        "warning",
        "critical",
    ]

    reason: str


class IncidentRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: int
    service: str

    severity: Literal[
        "info",
        "warning",
        "critical",
    ]

    reason: str

    status: Literal[
        "active",
        "resolved",
    ]

    created_at: datetime
    resolved_at: datetime | None


class DeploymentOperationRequest(BaseModel):
    slot: Literal[
        "blue",
        "green",
    ]

    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )

    git_sha: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )


class OperationStepRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: int
    position: int
    name: str

    status: Literal[
        "pending",
        "running",
        "success",
        "failed",
    ]

    created_at: datetime


class DeploymentOperationRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: int

    action: Literal[
        "deploy_healthy",
        "deploy_broken",
        "rollback",
    ]

    status: Literal[
        "queued",
        "running",
        "success",
        "failed",
    ]

    slot: str | None
    version: str | None
    git_sha: str | None

    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    steps: list[OperationStepRead]
