from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import RecoveryCode, RegistrationCode, User, UserSession, utcnow
from .security import (
    generate_one_time_code,
    hash_password,
    hash_token,
    validate_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_COOKIE = "tp_session"
ALLOWED_ROLES = {"student", "teacher"}


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: Literal["student", "teacher"]
    invite_code: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)

    @field_validator("username", "invite_code")
    @classmethod
    def strip_values(cls, value: str) -> str:
        return value.strip()


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role: Literal["student", "teacher"]


class RecoverPasswordRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    recovery_code: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


def _uniform_auth_error() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")


def _is_expired(value: datetime, now: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= now


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )


def _revoke_sessions(db: Session, user_id: str) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def get_current_user(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    if not session_token:
        raise HTTPException(status_code=401, detail="未登录")
    now = utcnow()
    session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == hash_token(session_token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    )
    if not session:
        raise HTTPException(status_code=401, detail="未登录")
    user = db.get(User, session.user_id)
    if not user or user.account_status != "active":
        raise HTTPException(status_code=401, detail="未登录")
    return user


def require_role(role: Literal["student", "teacher"]):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=403, detail="无权执行此操作")
        return user

    return dependency


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict[str, str | None]:
    return {"user_id": user.id, "username": user.username, "role": user.role, "display_name": user.display_name}


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = utcnow()
    invite = db.scalar(
        select(RegistrationCode)
        .where(RegistrationCode.code_hash == hash_token(payload.invite_code))
        .with_for_update()
    )
    if (
        not invite
        or invite.role not in ALLOWED_ROLES
        or invite.role != payload.role
        or invite.revoked_at is not None
        or _is_expired(invite.expires_at, now)
        or invite.used_count >= invite.max_uses
    ):
        raise HTTPException(status_code=400, detail="邀请码不可用")

    if db.scalar(select(User.id).where(User.username == payload.username)):
        raise HTTPException(status_code=400, detail="注册信息不可用")

    recovery_plain = generate_one_time_code("rc")
    user = User(
        username=payload.username,
        role=payload.role,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    db.add(
        RecoveryCode(
            user_id=user.id,
            code_hash=hash_token(recovery_plain),
            expires_at=now + timedelta(days=30),
        )
    )
    invite.used_count += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="注册信息不可用") from exc

    token = generate_one_time_code("sess")
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(seconds=get_settings().session_ttl_seconds),
        )
    )
    db.commit()
    _set_session_cookie(response, token)
    return {"user_id": user.id, "role": user.role, "recovery_code": recovery_plain}


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.scalar(select(User).where(User.username == payload.username))
    if (
        not user
        or user.account_status != "active"
        or user.role != payload.role
        or not verify_password(payload.password, user.password_hash)
    ):
        raise _uniform_auth_error()

    now = utcnow()
    token = generate_one_time_code("sess")
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(seconds=get_settings().session_ttl_seconds),
        )
    )
    db.commit()
    _set_session_cookie(response, token)
    return {"user_id": user.id, "role": user.role}


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Response:
    if session_token:
        db.execute(
            update(UserSession)
            .where(UserSession.token_hash == hash_token(session_token), UserSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/recover")
def recover_password(
    payload: RecoverPasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = utcnow()
    user = db.scalar(select(User).where(User.username == payload.username, User.account_status == "active"))
    recovery = None
    if user:
        recovery = db.scalar(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_hash == hash_token(payload.recovery_code),
                RecoveryCode.used_at.is_(None),
                RecoveryCode.expires_at > now,
            )
        )
    if not user or not recovery:
        raise HTTPException(status_code=400, detail="恢复凭证不可用")

    user.password_hash = hash_password(payload.new_password)
    recovery.used_at = now
    _revoke_sessions(db, user.id)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "password_updated"}
