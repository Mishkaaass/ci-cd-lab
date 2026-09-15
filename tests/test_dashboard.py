from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as app_module
from opsboard.database import Base, get_db
from opsboard.models import Deployment, Incident

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSession = sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSession()

    try:
        yield db
    finally:
        db.close()


client = TestClient(app_module.app)


def test_dashboard_renders_operational_data(monkeypatch):
    db = TestingSession()

    db.add(
        Deployment(
            version="v1.2.0",
            git_sha="abc1234",
            image="ghcr.io/mishkaaass/ci-cd-lab:sha-abc1234",
            status="success",
            duration_ms=4200,
        )
    )

    db.add(
        Incident(
            service="demo-api",
            severity="critical",
            reason="High latency detected",
            status="active",
        )
    )

    db.commit()
    db.close()

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

    app_module.app.dependency_overrides[get_db] = override_get_db

    try:
        response = client.get("/dashboard")
    finally:
        app_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "OpsBoard" in response.text
    assert "demo-api" in response.text
    assert "Healthy" in response.text
    assert "17.42 ms" in response.text
    assert "v1.2.0" in response.text
    assert "High latency detected" in response.text
