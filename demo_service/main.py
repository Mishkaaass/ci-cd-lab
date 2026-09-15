import os

from fastapi import FastAPI

app = FastAPI(
    title="OpsBoard Demo Service",
    version="0.1.0",
)


@app.get("/")
def home():
    return {
        "service": "demo-api",
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"status": "ready"}


@app.get("/version")
def version():
    return {
        "version": os.getenv("APP_VERSION", "dev"),
        "git_sha": os.getenv("GIT_SHA", "local"),
    }
