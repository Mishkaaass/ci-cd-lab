import json

import httpx
import pytest

from opsboard import history


def test_history_uses_header_without_redirects_or_environment_proxy(tmp_path):
    token = "a" * 43
    path = tmp_path / "operator.token"
    path.write_text(token)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + token
        assert str(request.url) == "http://127.0.0.1:8000/api/deployments"
        return httpx.Response(201, json={"id": 1})

    payload = {
        "version": "v1",
        "git_sha": "abc",
        "image": "demo:v1",
        "status": "success",
    }
    history.record(
        payload, "http://127.0.0.1:8000", path, transport=httpx.MockTransport(handler)
    )
    assert json.loads(calls[0].content) == payload


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.invalid",
        "https://user:pass@host",
        "https://host?token=x",
        "https://host/other",
        "file:///etc/passwd",
    ],
)
def test_history_refuses_unsafe_or_ambiguous_destination(tmp_path, url):
    with pytest.raises(ValueError):
        history.record({}, url, tmp_path / "absent")


def test_history_does_not_follow_redirects(tmp_path):
    path = tmp_path / "token"
    path.write_text("a" * 43)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://elsewhere.invalid"})

    with pytest.raises(httpx.HTTPStatusError):
        history.record(
            {}, "https://opsboard.example", path, transport=httpx.MockTransport(handler)
        )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://localhost",
        "https://user:pass@host",
        "https://host?x=y",
    ],
)
def test_release_verifier_rejects_non_http_or_credential_urls(url):
    from opsboard.release_verification import fetch_release_from_url

    with pytest.raises(ValueError):
        fetch_release_from_url(url)
