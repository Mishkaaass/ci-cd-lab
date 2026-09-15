from fastapi.testclient import TestClient

from demo_service.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_service_is_healthy(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "healthy")

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_fails_when_service_is_broken(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "broken")

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "simulated_deployment_failure",
    }


def test_version(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v2.0.0")
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("DEMO_MODE", "healthy")

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "version": "v2.0.0",
        "git_sha": "abc1234",
        "mode": "healthy",
    }


def test_probe_supports_real_latency(monkeypatch):
    monkeypatch.setenv("DEMO_LATENCY_MS", "50")

    response = client.get("/probe")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
