from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from opsboard.database import Base


class DeploymentOperationLock(Base):
    __tablename__ = "deployment_operation_locks"

    name: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
    )
