from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opsboard.database import Base


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    git_sha: Mapped[str] = mapped_column(String(64))
    image: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DeploymentOperation(Base):
    __tablename__ = "deployment_operations"

    id: Mapped[int] = mapped_column(primary_key=True)

    action: Mapped[str] = mapped_column(
        String(32),
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="queued",
    )

    slot: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    git_sha: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    steps: Mapped[list[OperationStep]] = relationship(
        back_populates="operation",
        cascade="all, delete-orphan",
        order_by="OperationStep.position",
    )


class OperationStep(Base):
    __tablename__ = "operation_steps"

    id: Mapped[int] = mapped_column(
        primary_key=True,
    )

    operation_id: Mapped[int] = mapped_column(
        ForeignKey("deployment_operations.id"),
    )

    position: Mapped[int] = mapped_column(
        Integer,
    )

    name: Mapped[str] = mapped_column(
        String(100),
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    operation: Mapped[DeploymentOperation] = relationship(
        back_populates="steps",
    )
