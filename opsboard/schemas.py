from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", check_fields=False)
    @classmethod
    def valid_text(cls, value):
        if isinstance(value, str) and any(
            char == "\x00" or 0xD800 <= ord(char) <= 0xDFFF for char in value
        ):
            raise ValueError("Unsupported text characters")
        return value


class DeploymentCreate(RecordInput):
    version: str = Field(min_length=1, max_length=64)
    git_sha: str = Field(min_length=1, max_length=64)
    image: str = Field(min_length=1, max_length=255)
    status: Literal[
        "deploying",
        "success",
        "failed",
        "rolled_back",
    ]
    duration_ms: int | None = Field(
        default=None,
        ge=0,
        le=2**31 - 1,
    )


class DeploymentRead(BaseModel):
    # Input hardening must not invalidate records accepted by older releases.
    version: str
    git_sha: str
    image: str
    status: Literal["deploying", "success", "failed", "rolled_back"]
    duration_ms: int | None = None
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: int
    created_at: datetime


class IncidentCreate(RecordInput):
    service: str = Field(min_length=1, max_length=100)

    severity: Literal[
        "info",
        "warning",
        "critical",
    ]

    reason: str = Field(min_length=1, max_length=255)


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
    model_config = ConfigDict(
        extra="forbid",
    )

    version: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )

    git_sha: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
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
