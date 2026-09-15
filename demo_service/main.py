import os
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="OpsBoard Demo Service",
    version="0.1.0",
)


def get_mode():
    return os.getenv(
        "DEMO_MODE",
        "healthy",
    )


@app.get("/")
def home():
    return {
        "service": "demo-api",
        "status": "running",
        "mode": get_mode(),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    if get_mode() == "broken":
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "reason": "simulated_deployment_failure",
            },
        )

    return {"status": "ready"}


@app.get("/probe")
def probe():
    latency_ms = int(
        os.getenv(
            "DEMO_LATENCY_MS",
            "0",
        )
    )

    if latency_ms > 0:
        time.sleep(latency_ms / 1000)

    return {"status": "ok"}


@app.get("/version")
def version():
    return {
        "version": os.getenv(
            "APP_VERSION",
            "dev",
        ),
        "git_sha": os.getenv(
            "GIT_SHA",
            "local",
        ),
        "mode": get_mode(),
    }
