from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app
from opsboard.database import Base, get_db

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

client = TestClient(app)


def override_get_db():
    db = TestingSession()

    try:
        yield db
    finally:
        db.close()


def test_incident_lifecycle():
    app.dependency_overrides[get_db] = override_get_db

    try:
        create_response = client.post(
            "/api/incidents",
            json={
                "service": "demo-api",
                "severity": "critical",
                "reason": "High latency detected",
            },
        )

        assert create_response.status_code == 201

        created = create_response.json()

        assert created["service"] == "demo-api"
        assert created["severity"] == "critical"
        assert created["reason"] == "High latency detected"
        assert created["status"] == "active"
        assert created["resolved_at"] is None

        incident_id = created["id"]

        list_response = client.get("/api/incidents")

        assert list_response.status_code == 200

        incidents = list_response.json()

        assert len(incidents) == 1
        assert incidents[0]["id"] == incident_id
        assert incidents[0]["status"] == "active"

        resolve_response = client.post(f"/api/incidents/{incident_id}/resolve")

        assert resolve_response.status_code == 200

        resolved = resolve_response.json()

        assert resolved["status"] == "resolved"
        assert resolved["resolved_at"] is not None

    finally:
        app.dependency_overrides.clear()
