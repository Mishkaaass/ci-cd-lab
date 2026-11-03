import json

import pytest
from sqlalchemy import func, select

from opsboard.models import Deployment, DeploymentOperation, Incident
from tests.security_support import OPERATOR_TOKEN, VIEWER_TOKEN

INCIDENT = {"service": "demo-api", "severity": "warning", "reason": "test"}
DEPLOYMENT = {
    "version": "v-test",
    "git_sha": "abc123",
    "image": "demo:test",
    "status": "success",
}
WRITES = [
    ("/api/incidents", INCIDENT),
    ("/api/deployments", DEPLOYMENT),
    ("/api/incidents/1/resolve", None),
    ("/api/operations/deploy-healthy", {"version": "v-test", "git_sha": "abc123"}),
    ("/api/operations/deploy-broken", {"version": "v-test", "git_sha": "abc123"}),
    ("/api/operations/rollback", None),
]


@pytest.mark.parametrize("path,payload", WRITES)
@pytest.mark.parametrize("role,status", [("anonymous", 401), ("viewer", 403)])
def test_unprivileged_write_has_no_side_effects(
    security_client, path, payload, role, status
):
    headers = {} if role == "anonymous" else {"Authorization": f"Bearer {VIEWER_TOKEN}"}
    response = security_client.client.post(path, json=payload, headers=headers)
    assert response.status_code == status
    assert security_client.db_calls == []
    assert security_client.dispatch_calls == []
    with security_client.sessions() as db:
        for model in (Incident, Deployment, DeploymentOperation):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "path",
    [
        "/api/incidents",
        "/api/deployments",
        "/api/operations",
        "/api/operations/1",
        "/api/services/demo",
        "/api/dashboard",
    ],
)
def test_private_reads_require_credentials_before_dependencies(security_client, path):
    response = security_client.client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert security_client.db_calls == []
    assert security_client.monitor_calls == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer incorrect"},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Cookie": f"token={OPERATOR_TOKEN}"},
        {"Authorization": "Bearer"},
    ],
)
def test_alternative_or_invalid_credentials_cannot_authenticate(
    security_client, headers
):
    response = security_client.client.get("/api/incidents", headers=headers)
    assert response.status_code == 401
    assert security_client.db_calls == []


def test_query_parameter_cannot_authenticate(security_client):
    response = security_client.client.get(
        "/api/incidents", params={"token": OPERATOR_TOKEN}
    )
    assert response.status_code == 401
    assert OPERATOR_TOKEN not in response.text


def test_expired_credential_cannot_authenticate(
    security_client, security_environment, operator_headers
):
    config = json.loads(security_environment.read_text())
    config[1]["expires_at"] = 1
    security_environment.write_text(json.dumps(config))
    response = security_client.client.get("/api/incidents", headers=operator_headers)
    assert response.status_code == 401
    assert security_client.db_calls == []


@pytest.mark.parametrize(
    "bad_config", [None, "not-json", "[]", '[{"role":"operator"}]']
)
def test_bad_configuration_fails_closed(
    security_client, security_environment, operator_headers, monkeypatch, bad_config
):
    if bad_config is None:
        monkeypatch.delenv("OPSBOARD_AUTH_FILE")
    else:
        security_environment.write_text(bad_config)
    response = security_client.client.get("/api/incidents", headers=operator_headers)
    assert response.status_code == 503
    assert security_client.db_calls == []


def test_valid_viewer_can_read_identity_and_records(security_client, viewer_headers):
    response = security_client.client.get("/api/auth/me", headers=viewer_headers)
    assert response.status_code == 200
    assert response.json()["role"] == "viewer"
    assert response.json()["name"] == "test-viewer"
    assert response.json()["can_write"] is False
    assert VIEWER_TOKEN not in response.text
    assert (
        security_client.client.get("/api/incidents", headers=viewer_headers).status_code
        == 200
    )


def test_operator_can_record_incident(security_client, operator_headers):
    response = security_client.client.post(
        "/api/incidents", json=INCIDENT, headers=operator_headers
    )
    assert response.status_code == 201


def test_deployment_execution_is_explicitly_disabled_by_default(
    security_client, operator_headers, monkeypatch
):
    monkeypatch.delenv("OPSBOARD_ENABLE_DEPLOYMENTS")
    response = security_client.client.post(
        "/api/operations/rollback", headers=operator_headers
    )
    assert response.status_code == 503
    assert security_client.dispatch_calls == []
    assert security_client.db_calls == []


def test_locked_dashboard_does_not_query_private_data(security_client):
    response = security_client.client.get("/dashboard")
    assert response.status_code == 200
    assert 'id="auth-form"' in response.text
    assert security_client.db_calls == []
    assert security_client.monitor_calls == []
