import os
from datetime import timedelta

os.environ.setdefault("SESSION_SECRET", "test-session-secret-012345678901234567890")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from teaching_platform.db import Base, get_db
from teaching_platform.main import app
from teaching_platform.models import RegistrationCode, utcnow
from teaching_platform.security import generate_one_time_code, hash_token

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base.metadata.create_all(engine)


def override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def make_invite(role: str = "student") -> str:
    code = generate_one_time_code("invite")
    db = SessionLocal()
    db.add(
        RegistrationCode(
            code_hash=hash_token(code),
            role=role,
            expires_at=utcnow() + timedelta(days=7),
            max_uses=2,
        )
    )
    db.commit()
    db.close()
    return code


def test_register_login_me_logout_and_cookie_flags() -> None:
    client = TestClient(app)
    response = client.post(
        "/auth/register",
        json={
            "username": "alice",
            "password": "a-strong-password-123",
            "role": "student",
            "invite_code": make_invite(),
            "display_name": "Alice",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "student"
    assert response.json()["recovery_code"].startswith("rc-")
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_role_mismatch_and_invalid_invite_are_rejected() -> None:
    client = TestClient(app)
    response = client.post(
        "/auth/register",
        json={
            "username": "bob",
            "password": "a-strong-password-123",
            "role": "teacher",
            "invite_code": make_invite("student"),
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "邀请码不可用"


def test_password_recovery_invalidates_old_session_and_code() -> None:
    client = TestClient(app)
    recovery = client.post(
        "/auth/register",
        json={
            "username": "carol",
            "password": "a-strong-password-123",
            "role": "student",
            "invite_code": make_invite(),
        },
    ).json()["recovery_code"]

    response = client.post(
        "/auth/recover",
        json={
            "username": "carol",
            "recovery_code": recovery,
            "new_password": "another-strong-password-123",
        },
    )
    assert response.status_code == 200
    assert client.get("/auth/me").status_code == 401
    assert client.post(
        "/auth/recover",
        json={
            "username": "carol",
            "recovery_code": recovery,
            "new_password": "yet-another-strong-password-123",
        },
    ).status_code == 400
