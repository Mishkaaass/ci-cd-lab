import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app
from opsboard.database import Base, get_db


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()

        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_queue_healthy_deployment(client):
    response = client.post(
        "/api/operations/deploy-healthy",
        json={
            "slot": "green",
            "version": "v2.1.0",
            "git_sha": "abc123",
        },
    )

    assert response.status_code == 202

    operation = response.json()

    assert operation["action"] == "deploy_healthy"
    assert operation["status"] == "queued"
    assert operation["slot"] == "green"
    assert operation["version"] == "v2.1.0"
    assert operation["git_sha"] == "abc123"

    assert [step["name"] for step in operation["steps"]] == [
        "Candidate selected",
        "Container started",
        "Readiness check",
        "Release identity verified",
        "Nginx configuration validated",
        "Traffic switched",
        "Production converged",
    ]

    assert all(step["status"] == "pending" for step in operation["steps"])


def test_second_active_operation_is_rejected(client):
    first = client.post(
        "/api/operations/deploy-healthy",
        json={
            "slot": "green",
            "version": "v2.1.0",
            "git_sha": "abc123",
        },
    )

    assert first.status_code == 202

    second = client.post(
        "/api/operations/deploy-broken",
        json={
            "slot": "blue",
            "version": "v2.1.1",
            "git_sha": "def456",
        },
    )

    assert second.status_code == 409
    assert second.json()["detail"] == ("Another deployment operation is already active")


def test_operation_can_be_read_by_id(client):
    created = client.post(
        "/api/operations/deploy-healthy",
        json={
            "slot": "green",
            "version": "v2.1.0",
            "git_sha": "abc123",
        },
    )

    operation_id = created.json()["id"]

    response = client.get(
        f"/api/operations/{operation_id}",
    )

    assert response.status_code == 200
    assert response.json()["id"] == operation_id
    assert response.json()["version"] == "v2.1.0"


def test_operations_can_be_listed(client):
    created = client.post(
        "/api/operations/deploy-healthy",
        json={
            "slot": "green",
            "version": "v2.1.0",
            "git_sha": "abc123",
        },
    )

    assert created.status_code == 202

    response = client.get("/api/operations")

    assert response.status_code == 200

    operations = response.json()

    assert len(operations) == 1
    assert operations[0]["action"] == "deploy_healthy"


def test_rollback_can_be_queued(client):
    response = client.post(
        "/api/operations/rollback",
    )

    assert response.status_code == 202

    operation = response.json()

    assert operation["action"] == "rollback"
    assert operation["status"] == "queued"
    assert operation["slot"] is None
    assert operation["version"] is None
    assert operation["git_sha"] is None

    assert [step["name"] for step in operation["steps"]] == [
        "Rollback target selected",
        "Target readiness verified",
        "Traffic switched",
        "Production converged",
    ]


def test_unknown_operation_returns_404(client):
    response = client.get("/api/operations/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Operation not found"
