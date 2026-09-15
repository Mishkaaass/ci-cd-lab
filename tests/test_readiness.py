from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import app
from opsboard.database import get_db

client = TestClient(app)


class HealthyDatabase:
    def execute(self, statement):
        return 1


class BrokenDatabase:
    def execute(self, statement):
        raise OperationalError(
            "SELECT 1",
            {},
            Exception("database unavailable"),
        )


def test_ready_when_database_is_available():
    def override_get_db():
        yield HealthyDatabase()

    app.dependency_overrides[get_db] = override_get_db

    response = client.get("/ready")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ok",
    }


def test_not_ready_when_database_is_unavailable():
    def override_get_db():
        yield BrokenDatabase()

    app.dependency_overrides[get_db] = override_get_db

    response = client.get("/ready")

    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "unavailable",
    }
