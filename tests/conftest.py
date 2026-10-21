import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.config import Settings


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/test.db",
        jwt_secret="test-jwt-secret-" * 4,
        collector_key="collector-test-" * 4,
        admin_password="test-admin-password",
        demo_enabled=True,
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def headers(client):
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    return {"Authorization": "Bearer " + response.json()["access_token"]}
