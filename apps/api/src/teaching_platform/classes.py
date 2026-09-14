from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import get_current_user, require_role
from .db import get_db
from .models import Class, ClassJoinCode, ClassMembership, User, utcnow
from .security import generate_one_time_code, hash_token

router = APIRouter(prefix="/classes", tags=["classes"])


class CreateClassRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=1, max_length=64)

    @field_validator("name", "subject")
    @classmethod
    def strip_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class JoinClassRequest(BaseModel):
    join_code: str = Field(min_length=8, max_length=256)

    @field_validator("join_code")
    @classmethod
    def strip_code(cls, value: str) -> str:
        return value.strip()


def _is_expired(value: datetime, now: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= now


def _class_payload(item: Class) -> dict[str, str]:
    return {"class_id": item.id, "name": item.name, "subject": item.subject, "status": item.status}


@router.post("", status_code=201)
def create_class(
    payload: CreateClassRequest,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    item = Class(teacher_id=teacher.id, name=payload.name, subject=payload.subject)
    db.add(item)
    db.commit()
    return _class_payload(item)


@router.get("")
def list_classes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, str]]:
    if user.role == "teacher":
        classes = db.scalars(select(Class).where(Class.teacher_id == user.id, Class.status == "active")).all()
    else:
        classes = db.scalars(
            select(Class)
            .join(ClassMembership, ClassMembership.class_id == Class.id)
            .where(ClassMembership.student_id == user.id, ClassMembership.status == "active", Class.status == "active")
        ).all()
    return [_class_payload(item) for item in classes]


@router.post("/{class_id}/join-code")
def create_join_code(
    class_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    item = db.scalar(select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id, Class.status == "active"))
    if not item:
        raise HTTPException(status_code=404, detail="班级不存在")

    now = utcnow()
    db.execute(
        update(ClassJoinCode)
        .where(ClassJoinCode.class_id == class_id, ClassJoinCode.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    plain_code = generate_one_time_code("class")
    db.add(
        ClassJoinCode(
            class_id=class_id,
            code_hash=hash_token(plain_code),
            expires_at=now + timedelta(days=30),
            max_uses=100,
        )
    )
    db.commit()
    return {"class_id": class_id, "join_code": plain_code, "expires_in_days": 30, "max_uses": 100}


@router.delete("/{class_id}/join-code", status_code=204)
def revoke_join_code(
    class_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> None:
    item = db.scalar(select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id, Class.status == "active"))
    if not item:
        raise HTTPException(status_code=404, detail="班级不存在")
    db.execute(
        update(ClassJoinCode)
        .where(ClassJoinCode.class_id == class_id, ClassJoinCode.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()


@router.post("/join")
def join_class(
    payload: JoinClassRequest,
    student: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    now = utcnow()
    if db.scalar(
        select(ClassMembership.id).where(ClassMembership.student_id == student.id, ClassMembership.status == "active")
    ):
        raise HTTPException(status_code=409, detail="学生已经加入班级")

    code = db.scalar(
        select(ClassJoinCode)
        .where(ClassJoinCode.code_hash == hash_token(payload.join_code))
        .with_for_update()
    )
    if (
        not code
        or code.revoked_at is not None
        or _is_expired(code.expires_at, now)
        or code.used_count >= code.max_uses
    ):
        raise HTTPException(status_code=400, detail="班级码不可用")

    item = db.scalar(select(Class).where(Class.id == code.class_id, Class.status == "active"))
    if not item:
        raise HTTPException(status_code=400, detail="班级码不可用")

    membership = ClassMembership(student_id=student.id, class_id=item.id, status="active")
    db.add(membership)
    code.used_count += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="学生已经加入班级") from exc
    return {"class_id": item.id, "name": item.name, "subject": item.subject, "status": membership.status}


@router.get("/{class_id}/members")
def list_members(
    class_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> list[dict[str, str | None]]:
    item = db.scalar(select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id, Class.status == "active"))
    if not item:
        raise HTTPException(status_code=404, detail="班级不存在")
    members = db.scalars(
        select(User)
        .join(ClassMembership, ClassMembership.student_id == User.id)
        .where(ClassMembership.class_id == class_id, ClassMembership.status == "active")
        .order_by(User.username)
    ).all()
    return [{"user_id": member.id, "username": member.username, "display_name": member.display_name} for member in members]
