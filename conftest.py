import hashlib
import json
import time

import pytest

from tests.security_support import OPERATOR_TOKEN, VIEWER_TOKEN


@pytest.fixture(autouse=True)
def security_environment(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    credentials = [
        {
            "name": name,
            "role": role,
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "expires_at": int(time.time()) + 3600,
        }
        for name, role, token in (
            ("test-viewer", "viewer", VIEWER_TOKEN),
            ("test-operator", "operator", OPERATOR_TOKEN),
        )
    ]
    path.write_text(json.dumps(credentials))
    monkeypatch.setenv("OPSBOARD_AUTH_FILE", str(path))
    monkeypatch.setenv(
        "OPSBOARD_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1,opsboard"
    )
    monkeypatch.setenv("OPSBOARD_RATE_LIMIT", "10000")
    monkeypatch.setenv("OPSBOARD_ENABLE_DEPLOYMENTS", "true")

    import app as app_module

    limiter = getattr(app_module.app.state, "request_limiter", None)
    if limiter is not None:
        limiter.clear()
    yield path
    if limiter is not None:
        limiter.clear()


@pytest.fixture
def operator_headers():
    return {"Authorization": f"Bearer {OPERATOR_TOKEN}"}


@pytest.fixture
def viewer_headers():
    return {"Authorization": f"Bearer {VIEWER_TOKEN}"}
