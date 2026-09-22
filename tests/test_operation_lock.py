from importlib import import_module
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from opsboard.database import Base


def make_session():
    import_module("opsboard.operation_lock")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    Session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    return Session()


def test_active_operation_lock_is_released_after_success():
    operations = import_module("opsboard.operations")
    executor = import_module("opsboard.operation_executor")
    lock_module = import_module("opsboard.operation_lock")

    with make_session() as db:
        first = operations.queue_operation(
            db,
            action="deploy_healthy",
            slot="green",
            version="v-first",
            git_sha="first123",
        )

        assert first is not None

        lock = db.get(
            lock_module.DeploymentOperationLock,
            operations.OPERATION_LOCK_NAME,
        )

        assert lock is not None

        blocked = operations.queue_operation(
            db,
            action="deploy_healthy",
            slot="blue",
            version="v-blocked",
            git_sha="blocked123",
        )

        assert blocked is None

        executor.execute_operation(
            db,
            first.id,
            runner=lambda **kwargs: SimpleNamespace(
                returncode=0,
            ),
        )

        lock = db.get(
            lock_module.DeploymentOperationLock,
            operations.OPERATION_LOCK_NAME,
        )

        assert lock is None

        second = operations.queue_operation(
            db,
            action="deploy_healthy",
            slot="blue",
            version="v-second",
            git_sha="second123",
        )

        assert second is not None
