import os

os.environ.setdefault("SESSION_SECRET", "test-session-secret-012345678901234567890")

from fastapi.testclient import TestClient

from teaching_platform.main import app


def test_healthz() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_readyz_requires_valid_session_secret() -> None:
    response = TestClient(app).get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"

