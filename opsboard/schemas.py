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
    duration_ms: int | None = Field(default=None, ge=0)


class DeploymentRead(DeploymentCreate):
    model_config = ConfigDict(from_attributes=True)

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
    model_config = ConfigDict(from_attributes=True)

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
