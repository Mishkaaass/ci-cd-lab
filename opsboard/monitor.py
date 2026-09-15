import os
import time

import httpx


def fetch_demo_service_status(base_url=None, client=None):
    base_url = base_url or os.getenv(
        "DEMO_SERVICE_URL",
        "http://127.0.0.1:8001",
    )

    owns_client = client is None

    if owns_client:
        client = httpx.Client(timeout=3.0)

    try:
        health_response = client.get(f"{base_url}/health")

        ready_response = client.get(f"{base_url}/ready")

        start = time.perf_counter()

        probe_response = client.get(f"{base_url}/probe")

        latency_ms = round(
            (time.perf_counter() - start) * 1000,
            2,
        )

        version_response = client.get(f"{base_url}/version")

        healthy = (
            health_response.status_code == 200
            and health_response.json().get("status") == "ok"
        )

        ready = (
            ready_response.status_code == 200
            and ready_response.json().get("status") == "ready"
        )

        probe_ok = probe_response.status_code == 200

        version_data = version_response.json()

        if healthy and ready and probe_ok:
            status = "healthy"
        elif healthy:
            status = "degraded"
        else:
            status = "down"

        return {
            "name": "demo-api",
            "status": status,
            "ready": ready,
            "latency_ms": latency_ms,
            "version": version_data.get(
                "version",
                "unknown",
            ),
            "git_sha": version_data.get(
                "git_sha",
                "unknown",
            ),
        }

    except httpx.HTTPError:
        return {
            "name": "demo-api",
            "status": "down",
            "ready": False,
            "latency_ms": None,
            "version": "unknown",
            "git_sha": "unknown",
        }

    finally:
        if owns_client:
            client.close()
