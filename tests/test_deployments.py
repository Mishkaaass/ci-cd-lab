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

TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


def test_create_and_list_deployment():
    payload = {
        "version": "v1.2.0",
        "git_sha": "abc1234",
        "image": "ghcr.io/mishkaaass/ci-cd-lab:sha-abc1234",
        "status": "success",
        "duration_ms": 4200,
    }

    created = client.post("/api/deployments", json=payload)

    assert created.status_code == 201
    assert created.json()["version"] == "v1.2.0"
    assert created.json()["status"] == "success"

    deployments = client.get("/api/deployments")

    assert deployments.status_code == 200
    assert len(deployments.json()) == 1
    assert deployments.json()[0]["git_sha"] == "abc1234"
