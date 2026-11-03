import json

import pytest

from tests.security_support import OPERATOR_TOKEN


def test_security_headers_on_dashboard(security_client):
    response = security_client.client.get("/dashboard")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_untrusted_host_is_rejected(security_client, operator_headers):
    response = security_client.client.get(
        "/api/incidents", headers={**operator_headers, "Host": "attacker.invalid"}
    )
    assert response.status_code == 400
    assert security_client.db_calls == []


def test_duplicate_authorization_is_rejected(security_client):
    response = security_client.client.get(
        "/api/incidents",
        headers=[
            ("Authorization", "Bearer incorrect"),
            ("Authorization", f"Bearer {OPERATOR_TOKEN}"),
        ],
    )
    assert response.status_code == 401
    assert security_client.db_calls == []


def test_oversized_body_is_rejected_before_database(security_client, operator_headers):
    response = security_client.client.post(
        "/api/incidents",
        content=json.dumps({"reason": "x" * 20000}),
        headers={**operator_headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert security_client.db_calls == []


def test_unknown_fields_do_not_create_records(security_client, operator_headers):
    response = security_client.client.post(
        "/api/incidents",
        json={
            "service": "demo",
            "severity": "warning",
            "reason": "test",
            "id": 999,
        },
        headers=operator_headers,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("service", "x" * 101),
        ("reason", "x" * 256),
        ("service", ""),
        ("reason", "nul\x00text"),
        ("reason", "surrogate\ud800"),
    ],
)
def test_invalid_incident_text_is_a_client_error(
    security_client, operator_headers, field, value
):
    payload = {"service": "demo", "severity": "warning", "reason": "test"}
    payload[field] = value
    # JSON escapes permit testing surrogate code points without client UTF-8 failure.
    response = security_client.client.post(
        "/api/incidents",
        content=json.dumps(payload),
        headers={**operator_headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "x" * 65),
        ("git_sha", "x" * 65),
        ("image", "x" * 256),
        ("duration_ms", 2**31),
        ("duration_ms", -1),
    ],
)
def test_invalid_deployment_record_is_rejected(
    security_client, operator_headers, field, value
):
    payload = {
        "version": "v1",
        "git_sha": "abc",
        "image": "demo:v1",
        "status": "success",
        "duration_ms": 1,
    }
    payload[field] = value
    assert (
        security_client.client.post(
            "/api/deployments", json=payload, headers=operator_headers
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "path", ["/api/incidents/-1/resolve", f"/api/incidents/{2**80}/resolve"]
)
def test_invalid_database_identifier_is_rejected(
    security_client, operator_headers, path
):
    assert (
        security_client.client.post(path, headers=operator_headers).status_code == 422
    )


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=10001"])
def test_pagination_is_bounded(security_client, viewer_headers, query):
    for path in ("/api/incidents", "/api/deployments", "/api/operations"):
        assert (
            security_client.client.get(
                f"{path}?{query}", headers=viewer_headers
            ).status_code
            == 422
        )


def test_request_limit_is_enforced(security_client, operator_headers, monkeypatch):
    monkeypatch.setenv("OPSBOARD_RATE_LIMIT", "3")
    for _ in range(3):
        assert (
            security_client.client.get(
                "/api/incidents", headers=operator_headers
            ).status_code
            == 200
        )
    response = security_client.client.get("/api/incidents", headers=operator_headers)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_readiness_fails_without_authentication_config(security_client, monkeypatch):
    monkeypatch.delenv("OPSBOARD_AUTH_FILE")
    assert security_client.client.get("/health").status_code == 200
    assert security_client.client.get("/ready").status_code == 503


def test_audit_logs_exclude_credentials_and_query(
    security_client, operator_headers, caplog
):
    response = security_client.client.post(
        "/api/incidents?secret=never-log-this",
        json={
            "service": "demo",
            "severity": "warning",
            "reason": "private body never-log-this-body",
        },
        headers=operator_headers,
    )
    assert response.status_code == 201
    logs = "\n".join(r.message for r in caplog.records if r.name == "opsboard.audit")
    assert "test-operator" in logs
    assert "request_id" in logs
    assert OPERATOR_TOKEN not in logs
    assert "never-log-this" not in logs


def test_internal_monitor_does_not_inherit_proxy_settings(monkeypatch):
    import httpx

    from opsboard.monitor import fetch_demo_service_status

    calls = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def get(self, _url):
            raise httpx.ConnectError("unavailable")

        def close(self):
            pass

    monkeypatch.setattr("opsboard.monitor.httpx.Client", Client)
    assert fetch_demo_service_status()["status"] == "down"
    assert calls[0]["trust_env"] is False
