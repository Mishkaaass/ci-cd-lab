from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_home_endpoint():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "OpsBoard API",
        "status": "running",
    }


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_endpoint(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v1.2.3")
    monkeypatch.setenv("GIT_SHA", "abc1234")

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": "v1.2.3",
        "git_sha": "abc1234",
    }
