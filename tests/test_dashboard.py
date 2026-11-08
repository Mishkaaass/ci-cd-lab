import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as app_module
from opsboard.database import Base, get_db
from opsboard.models import Deployment, Incident
from opsboard.operations import create_operation


@pytest.fixture
def client(viewer_headers):
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

    app_module.app.dependency_overrides[get_db] = override_get_db

    try:
        yield (
            TestClient(
                app_module.app,
                headers=viewer_headers,
            ),
            testing_session,
        )
    finally:
        app_module.app.dependency_overrides.clear()

        Base.metadata.drop_all(
            bind=engine,
        )

        engine.dispose()


def test_dashboard_renders_operational_data(
    client,
    monkeypatch,
):
    test_client, testing_session = client

    with testing_session() as db:
        db.add(
            Deployment(
                version="v1.2.0",
                git_sha="abc1234",
                image=("ghcr.io/mishkaaass/ci-cd-lab:sha-abc1234"),
                status="success",
                duration_ms=4200,
            )
        )

        db.add(
            Incident(
                service="demo-api",
                severity="critical",
                reason=("High latency detected"),
                status="active",
            )
        )

        create_operation(
            db,
            action="deploy_healthy",
            slot="green",
            version="v2.0.0",
            git_sha="release200",
            step_names=[
                "Candidate selected",
                "Container started",
                "Readiness check",
            ],
        )

        db.commit()

    monkeypatch.setattr(
        app_module,
        "fetch_demo_service_status",
        lambda: {
            "name": "demo-api",
            "status": "healthy",
            "ready": True,
            "latency_ms": 17.42,
            "version": "v1.2.0",
            "git_sha": "abc1234",
        },
    )

    response = test_client.get(
        "/dashboard",
    )

    assert response.status_code == 200

    html = response.text

    assert "OpsBoard" in html
    assert "High latency detected" not in html
    assert "v1.2.0" not in html
    data_response = test_client.get("/api/dashboard")
    assert data_response.status_code == 200
    data = data_response.json()
    assert data["service"]["name"] == "demo-api"
    assert data["service"]["status"] == "healthy"
    assert data["service"]["latency_ms"] == 17.42
    assert data["deployments"][0]["version"] == "v1.2.0"
    assert data["incidents"][0]["reason"] == "High latency detected"
    assert data["active_incident_count"] == 1

    assert "Deployment Control" in html
    assert "Deploy Healthy" in html
    assert "Deploy Broken" in html
    assert "Rollback" in html

    assert "Automatic inactive slot" in html

    assert 'id="deployment-slot"' not in html

    assert "Live Deployment Timeline" in html

    operation = data["operations"][0]
    assert [step["name"] for step in operation["steps"]] == [
        "Candidate selected",
        "Container started",
        "Readiness check",
    ]
    assert operation["version"] == "v2.0.0"
    assert operation["git_sha"] == "release200"

    assert "/static/dashboard.js" in html


def test_local_lab_route_is_read_only_and_matches_config(tmp_path, monkeypatch):
    config = tmp_path / "active_backend.inc"
    config.write_text("server demo-green:8000;\n")
    monkeypatch.setattr(app_module, "NGINX_ACTIVE_BACKEND_CONFIG", config)
    assert app_module.configured_active_lab_slot() == "green"
    config.write_text("server demo-blue:8000;\n")
    assert app_module.configured_active_lab_slot() == "blue"
    config.write_text("server demo-blue:8000;\nserver demo-green:8000;\n")
    assert app_module.configured_active_lab_slot() is None
    config.unlink()
    assert app_module.configured_active_lab_slot() is None


def test_dashboard_explains_local_cli_vs_api_history(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    test_client, _session = client
    response = test_client.get("/dashboard")
    assert response.status_code == 200
    assert "Guided Local Lab" in response.text or "GUIDED WALKTHROUGH" in response.text
    assert "Actual CLI release history" in response.text
    assert "API-queued operations appear here" in response.text


def test_dashboard_api_reports_configured_route(client, tmp_path, monkeypatch):
    test_client, _session = client
    config = tmp_path / "active_backend.inc"
    config.write_text("server demo-green:8000;\n")
    monkeypatch.setattr(app_module, "NGINX_ACTIVE_BACKEND_CONFIG", config)
    monkeypatch.setattr(
        app_module,
        "fetch_demo_service_status",
        lambda: {
            "name": "demo-api", "status": "healthy", "ready": True,
            "latency_ms": 4, "version": "v2", "git_sha": "sha123",
        },
    )
    response = test_client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["local_lab"]["configured_active_slot"] == "green"
    assert response.json()["local_lab"]["control_mode"] == "api"
