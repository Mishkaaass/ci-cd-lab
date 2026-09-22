from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from opsboard.database import Base


def make_session():
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


def make_file_session_factory(tmp_path):
    database_path = tmp_path / "operations.db"

    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={
            "check_same_thread": False,
            "timeout": 5.0,
        },
    )

    Base.metadata.create_all(engine)

    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )


def test_deployment_operation_can_persist_with_ordered_steps():
    models = import_module("opsboard.models")

    DeploymentOperation = models.DeploymentOperation
    OperationStep = models.OperationStep

    with make_session() as db:
        operation = DeploymentOperation(
            action="deploy_healthy",
            status="queued",
        )

        operation.steps = [
            OperationStep(
                position=1,
                name="Candidate selected",
                status="success",
            ),
            OperationStep(
                position=2,
                name="Container started",
                status="pending",
            ),
        ]

        db.add(operation)
        db.commit()
        db.refresh(operation)

        assert operation.id is not None
        assert operation.action == "deploy_healthy"
        assert operation.status == "queued"

        assert len(operation.steps) == 2

        assert operation.steps[0].position == 1
        assert operation.steps[0].name == "Candidate selected"
        assert operation.steps[0].status == "success"

        assert operation.steps[1].position == 2
        assert operation.steps[1].name == "Container started"
        assert operation.steps[1].status == "pending"


def test_create_operation_builds_pending_timeline():
    operations = import_module("opsboard.operations")

    with make_session() as db:
        operation = operations.create_operation(
            db,
            action="deploy_healthy",
            step_names=[
                "Candidate selected",
                "Container started",
                "Readiness check",
            ],
        )

        assert operation.id is not None
        assert operation.action == "deploy_healthy"
        assert operation.status == "queued"

        assert [
            (
                step.position,
                step.name,
                step.status,
            )
            for step in operation.steps
        ] == [
            (
                1,
                "Candidate selected",
                "pending",
            ),
            (
                2,
                "Container started",
                "pending",
            ),
            (
                3,
                "Readiness check",
                "pending",
            ),
        ]


def test_operation_schema_serializes_database_operation():
    operations = import_module("opsboard.operations")
    schemas = import_module("opsboard.schemas")

    assert hasattr(
        schemas,
        "DeploymentOperationRead",
    ), "DeploymentOperationRead schema is missing"

    with make_session() as db:
        operation = operations.create_operation(
            db,
            action="deploy_healthy",
            step_names=[
                "Candidate selected",
                "Readiness check",
            ],
        )

        result = schemas.DeploymentOperationRead.model_validate(
            operation,
        )

        assert result.id == operation.id
        assert result.action == "deploy_healthy"
        assert result.status == "queued"

        assert len(result.steps) == 2

        assert result.steps[0].position == 1
        assert result.steps[0].name == "Candidate selected"
        assert result.steps[0].status == "pending"

        assert result.steps[1].position == 2
        assert result.steps[1].name == "Readiness check"
        assert result.steps[1].status == "pending"


def test_queue_operation_allows_only_one_concurrent_active_operation(
    tmp_path,
    monkeypatch,
):
    operations = import_module("opsboard.operations")

    Session = make_file_session_factory(
        tmp_path,
    )

    race_barrier = Barrier(2)

    original_get_active_operation = operations.get_active_operation

    def synchronized_get_active_operation(db):
        active_operation = original_get_active_operation(db)

        # End the read transaction before both workers
        # enter the write phase. This makes the test
        # reproduce the application-level race instead
        # of a SQLite locking artifact.
        db.rollback()

        race_barrier.wait(
            timeout=5,
        )

        return active_operation

    monkeypatch.setattr(
        operations,
        "get_active_operation",
        synchronized_get_active_operation,
    )

    def queue_deployment():
        with Session() as db:
            return operations.queue_operation(
                db,
                action="deploy_healthy",
                slot="green",
                version="v-race",
                git_sha="race123",
            )

    with ThreadPoolExecutor(
        max_workers=2,
    ) as executor:
        futures = [
            executor.submit(
                queue_deployment,
            )
            for _ in range(2)
        ]

        results = [
            future.result(
                timeout=10,
            )
            for future in futures
        ]

    accepted_count = sum(result is not None for result in results)

    rejected_count = sum(result is None for result in results)

    assert accepted_count == 1
    assert rejected_count == 1

    with Session() as db:
        active_operations = [
            operation
            for operation in operations.list_operations(
                db,
            )
            if operation.status in operations.ACTIVE_OPERATION_STATUSES
        ]

        assert len(active_operations) == 1
