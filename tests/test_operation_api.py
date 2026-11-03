import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as app_module
from opsboard.database import Base, get_db


@pytest.fixture
def dispatch_calls():
    return []


@pytest.fixture
def client(
    operator_headers,
    dispatch_calls,
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    Base.metadata.create_all(
        bind=engine,
    )

    def override_get_db():
        db = testing_session()

        try:
            yield db
        finally:
            db.close()

    def fake_dispatcher(operation_id):
        dispatch_calls.append(
            operation_id,
        )

    def override_dispatcher():
        return fake_dispatcher

    app_module.app.dependency_overrides[get_db] = override_get_db

    app_module.app.dependency_overrides[app_module.get_operation_dispatcher] = (
        override_dispatcher
    )

    monkeypatch.setattr(
        app_module,
        "resolve_inactive_slot",
        lambda *args, **kwargs: "green",
        raising=False,
    )

    try:
        yield TestClient(
            app_module.app,
            headers=operator_headers,
        )
    finally:
        app_module.app.dependency_overrides.clear()
        Base.metadata.drop_all(
            bind=engine,
        )
        engine.dispose()


def test_resolve_inactive_slot_from_nginx_config(
    tmp_path,
):
    assert hasattr(
        app_module,
        "resolve_inactive_slot",
    ), "resolve_inactive_slot is missing"

    config_path = tmp_path / "active_backend.inc"

    config_path.write_text("server demo-blue:8000;\n")

    assert (
        app_module.resolve_inactive_slot(
            config_path,
        )
        == "green"
    )

    config_path.write_text("server demo-green:8000;\n")

    assert (
        app_module.resolve_inactive_slot(
            config_path,
        )
        == "blue"
    )


def test_queue_healthy_deployment_uses_inactive_slot(
    client,
):
    response = client.post(
        "/api/operations/deploy-healthy",
        json={
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


def test_backend_can_select_blue_when_green_is_active(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        app_module,
        "resolve_inactive_slot",
        lambda *args, **kwargs: "blue",
    )

    response = client.post(
        "/api/operations/deploy-healthy",
        json={
            "version": "v2.2.0",
            "git_sha": "release220",
        },
    )

    assert response.status_code == 202

    assert response.json()["slot"] == "blue"


def test_browser_cannot_choose_deployment_slot(
    client,
):
    response = client.post(
        "/api/operations/deploy-healthy",
        json={
            "slot": "blue",
            "version": "v2.1.0",
            "git_sha": "abc123",
        },
    )

    assert response.status_code == 422


def test_healthy_deployment_is_dispatched(
    client,
    dispatch_calls,
):
    response = client.post(
        "/api/operations/deploy-healthy",
        json={
            "version": "v2.2.0",
            "git_sha": "release220",
        },
    )

    assert response.status_code == 202

    operation_id = response.json()["id"]

    assert dispatch_calls == [
        operation_id,
    ]


def test_second_active_operation_is_rejected(
    client,
):
    first = client.post(
        "/api/operations/deploy-healthy",
        json={
            "version": "v2.1.0",
            "git_sha": "abc123",
        },
    )

    assert first.status_code == 202

    second = client.post(
        "/api/operations/deploy-broken",
        json={
            "version": "v2.1.1",
            "git_sha": "def456",
        },
    )

    assert second.status_code == 409

    assert second.json()["detail"] == ("Another deployment operation is already active")


def test_operation_can_be_read_by_id(
    client,
):
    created = client.post(
        "/api/operations/deploy-healthy",
        json={
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


def test_operations_can_be_listed(
    client,
):
    created = client.post(
        "/api/operations/deploy-healthy",
        json={
            "version": "v2.1.0",
            "git_sha": "abc123",
        },
    )

    assert created.status_code == 202

    response = client.get(
        "/api/operations",
    )

    assert response.status_code == 200

    operations = response.json()

    assert len(operations) == 1

    assert operations[0]["action"] == "deploy_healthy"


def test_rollback_can_be_queued(
    client,
):
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


def test_unknown_operation_returns_404(
    client,
):
    response = client.get(
        "/api/operations/999",
    )

    assert response.status_code == 404

    assert response.json()["detail"] == "Operation not found"
