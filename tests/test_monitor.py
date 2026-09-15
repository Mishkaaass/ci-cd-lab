import httpx

from opsboard.monitor import fetch_demo_service_status


def test_fetch_demo_service_status():
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={"status": "ok"},
            )

        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={"status": "ready"},
            )

        if request.url.path == "/probe":
            return httpx.Response(
                200,
                json={"status": "ok"},
            )

        if request.url.path == "/version":
            return httpx.Response(
                200,
                json={
                    "version": "v1.0.0",
                    "git_sha": "abc1234",
                    "mode": "healthy",
                },
            )

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    with httpx.Client(transport=transport) as client:
        result = fetch_demo_service_status(
            "http://demo-service",
            client=client,
        )

    assert result["name"] == "demo-api"
    assert result["status"] == "healthy"
    assert result["ready"] is True
    assert result["version"] == "v1.0.0"
    assert result["git_sha"] == "abc1234"
    assert result["latency_ms"] >= 0
