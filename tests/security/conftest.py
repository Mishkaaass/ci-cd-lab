import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateSchema, DropSchema

import app as app_module
from opsboard.database import Base, get_db


@pytest.fixture
def security_client(monkeypatch):
    database_url = os.getenv("SECURITY_DATABASE_URL")
    schema = None
    if database_url:
        url = make_url(database_url)
        if (
            url.get_backend_name() != "postgresql"
            or url.database != "opsboard_security_test"
        ):
            pytest.fail(
                "Security tests require a dedicated opsboard_security_test database"
            )
        original_engine = create_engine(database_url)
        schema = "security_test_" + uuid.uuid4().hex
        with original_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = original_engine.execution_options(schema_translate_map={None: schema})
    else:
        original_engine = engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    dispatch_calls = []
    db_calls = []
    monitor_calls = []

    def get_test_db():
        db_calls.append(True)
        with sessions() as db:
            yield db

    def monitor():
        monitor_calls.append(True)
        return {
            "name": "demo-api",
            "status": "healthy",
            "ready": True,
            "latency_ms": 1,
            "version": "v-test",
            "git_sha": "test123",
        }

    app_module.app.dependency_overrides[get_db] = get_test_db
    app_module.app.dependency_overrides[app_module.get_operation_dispatcher] = lambda: (
        dispatch_calls.append
    )
    monkeypatch.setattr(app_module, "resolve_inactive_slot", lambda: "green")
    monkeypatch.setattr(app_module, "fetch_demo_service_status", monitor)
    try:
        yield SimpleNamespace(
            client=TestClient(app_module.app, raise_server_exceptions=False),
            sessions=sessions,
            dispatch_calls=dispatch_calls,
            db_calls=db_calls,
            monitor_calls=monitor_calls,
        )
    finally:
        app_module.app.dependency_overrides.clear()
        if schema:
            # This unique schema was created above in the dedicated test database.
            with original_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        original_engine.dispose()
