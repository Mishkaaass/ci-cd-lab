import pytest
from sqlalchemy import func, select

from opsboard.deployment_runner import DeploymentActionError, build_command
from opsboard.models import Incident


@pytest.mark.parametrize(
    "payload",
    [
        "' OR '1'='1",
        "x' UNION SELECT current_user --",
        "x'); SELECT pg_sleep(0); --",
        "quotation ' and semicolon ; stay data",
    ],
)
def test_sql_payload_is_literal_and_does_not_change_other_records(
    security_client, operator_headers, payload
):
    original = security_client.client.post(
        "/api/incidents",
        json={
            "service": "original",
            "severity": "warning",
            "reason": "keep this record",
        },
        headers=operator_headers,
    ).json()
    result = security_client.client.post(
        "/api/incidents",
        json={
            "service": "test",
            "severity": "warning",
            "reason": payload,
        },
        headers=operator_headers,
    )
    assert result.status_code == 201
    assert result.json()["reason"] == payload
    with security_client.sessions() as db:
        assert db.get(Incident, original["id"]).reason == "keep this record"
        assert db.scalar(select(func.count()).select_from(Incident)) == 2
    rows = security_client.client.get("/api/incidents", headers=operator_headers).json()
    assert rows[0]["reason"] == payload
    assert rows[1]["service"] == "original"


def test_stored_html_is_data_and_never_in_public_shell(
    security_client, operator_headers
):
    payload = '<img src=x onerror="window.__opsboard_xss=1">'
    result = security_client.client.post(
        "/api/incidents",
        json={
            "service": "test",
            "severity": "warning",
            "reason": payload,
        },
        headers=operator_headers,
    )
    assert result.status_code == 201
    data = security_client.client.get("/api/dashboard", headers=operator_headers)
    assert data.json()["incidents"][0]["reason"] == payload
    shell = security_client.client.get("/dashboard")
    assert payload not in shell.text
    assert "window.__opsboard_xss" not in shell.text


@pytest.mark.parametrize(
    "payload",
    [
        "--help",
        ".",
        "..",
        "-v1",
        "x" * 65,
        "v1; printf marker",
        "$(printf marker)",
        "v1\nnext",
        "../version",
    ],
)
def test_release_argument_cannot_be_an_option_path_or_shell_syntax(payload):
    with pytest.raises(DeploymentActionError):
        build_command(
            action="deploy_healthy", slot="green", version=payload, git_sha="abc123"
        )


@pytest.mark.parametrize(
    "path",
    [
        "/static/%2e%2e/app.py",
        "/static/%2e%2e/opsboard/database.py",
        "/static/%2e%2e%2fapp.py",
        "/static/%2e%2e%5capp.py",
    ],
)
def test_static_traversal_does_not_return_source(security_client, path):
    response = security_client.client.get(path)
    assert response.status_code == 404
    assert "import os" not in response.text
    assert "DATABASE_URL" not in response.text


def test_records_are_paginated_in_the_database(security_client, viewer_headers):
    with security_client.sessions() as db:
        db.add_all(
            Incident(service="test", severity="warning", reason=f"row-{i}")
            for i in range(105)
        )
        db.commit()
    default = security_client.client.get(
        "/api/incidents", headers=viewer_headers
    ).json()
    second = security_client.client.get(
        "/api/incidents?limit=5&offset=100", headers=viewer_headers
    ).json()
    assert len(default) == 100
    assert len(second) == 5
    assert {item["id"] for item in default}.isdisjoint(item["id"] for item in second)


def test_legacy_empty_deployment_fields_remain_readable(
    security_client, viewer_headers
):
    from opsboard.models import Deployment

    with security_client.sessions() as db:
        db.add(Deployment(version="", git_sha="", image="", status="success"))
        db.commit()
    records = security_client.client.get("/api/deployments", headers=viewer_headers)
    assert records.status_code == 200
    assert records.json()[0]["version"] == ""
    dashboard = security_client.client.get("/api/dashboard", headers=viewer_headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["deployments"][0]["image"] == ""
