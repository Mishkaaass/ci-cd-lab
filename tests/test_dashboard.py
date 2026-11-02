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
