from fastapi.testclient import TestClient

from demo_service.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready():
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_version(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v2.0.0")
    monkeypatch.setenv("GIT_SHA", "abc1234")

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": "v2.0.0",
        "git_sha": "abc1234",
    }
