from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, require_role
from .db import get_db
from .models import Assignment, AssignmentQuestion, Class, ClassMembership, User, utcnow

router = APIRouter(prefix="/assignments", tags=["assignments"])


class QuestionRequest(BaseModel):
    question_type: Literal["choice", "fill", "short", "short_answer"]
    prompt: str = Field(min_length=1, max_length=10000)
    options: list[str] | None = Field(default=None, max_length=20)
    correct_answer: str | None = Field(default=None, max_length=10000)
    max_score: int | None = Field(default=None, ge=1)
    rubric: str | None = Field(default=None, max_length=10000)

    @field_validator("prompt", "correct_answer", "rubric", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [item.strip() for item in value]
        if not cleaned or any(not item for item in cleaned):
            raise ValueError("选项不能为空")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("选项不能重复")
        return cleaned

    @model_validator(mode="after")
    def validate_type_fields(self) -> "QuestionRequest":
        question_type = "short" if self.question_type == "short_answer" else self.question_type
        if question_type == "choice" and not self.options:
            raise ValueError("选择题必须提供选项")
        if question_type == "short" and (self.max_score is None or not self.rubric):
            raise ValueError("简答题必须提供正整数满分和评分要点")
        return self


class CreateAssignmentRequest(BaseModel):
    class_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    subject: str | None = Field(default=None, max_length=64)
    due_at: datetime | None = None
    questions: list[QuestionRequest] = Field(min_length=1, max_length=200)

    @field_validator("title", "description", "subject", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


def _question_payload(question: AssignmentQuestion, *, include_answers: bool) -> dict:
    payload = {
        "question_id": question.id,
        "position": question.position,
        "question_type": question.question_type,
        "prompt": question.prompt,
        "options": question.options,
    }
    if include_answers:
        payload.update(
            {
                "correct_answer": question.correct_answer,
                "max_score": question.max_score,
                "rubric": question.rubric,
            }
        )
    return payload


def _assignment_payload(item: Assignment, questions: list[AssignmentQuestion], *, include_answers: bool) -> dict:
    return {
        "assignment_id": item.id,
        "class_id": item.class_id,
        "teacher_id": item.teacher_id,
        "title": item.title,
        "description": item.description,
        "subject": item.subject,
        "due_at": item.due_at,
        "status": item.status,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "published_at": item.published_at,
        "questions": [_question_payload(q, include_answers=include_answers) for q in questions],
    }


def _load_questions(db: Session, assignment_id: str) -> list[AssignmentQuestion]:
    return db.scalars(
        select(AssignmentQuestion)
        .where(AssignmentQuestion.assignment_id == assignment_id)
        .order_by(AssignmentQuestion.position)
    ).all()


def _teacher_assignment(db: Session, assignment_id: str, teacher_id: str) -> Assignment:
    item = db.scalar(
        select(Assignment)
        .join(Class, Class.id == Assignment.class_id)
        .where(
            Assignment.id == assignment_id,
            Assignment.teacher_id == teacher_id,
            Class.teacher_id == teacher_id,
            Class.status == "active",
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="作业不存在")
    return item


@router.post("", status_code=201)
def create_assignment(
    payload: CreateAssignmentRequest,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict:
    target_class = db.scalar(
        select(Class).where(
            Class.id == payload.class_id,
            Class.teacher_id == teacher.id,
            Class.status == "active",
        )
    )
    if not target_class:
        raise HTTPException(status_code=404, detail="班级不存在")
    if payload.subject and payload.subject != target_class.subject:
        raise HTTPException(status_code=400, detail="作业科目必须与班级一致")

    item = Assignment(
        class_id=target_class.id,
        teacher_id=teacher.id,
        title=payload.title,
        description=payload.description,
        subject=payload.subject or target_class.subject,
        due_at=payload.due_at,
    )
    db.add(item)
    db.flush()
    for position, question in enumerate(payload.questions, start=1):
        question_type = "short" if question.question_type == "short_answer" else question.question_type
        db.add(
            AssignmentQuestion(
                assignment_id=item.id,
                position=position,
                question_type=question_type,
                prompt=question.prompt,
                options=question.options,
                correct_answer=question.correct_answer,
                max_score=question.max_score,
                rubric=question.rubric,
            )
        )
    db.commit()
    return _assignment_payload(item, _load_questions(db, item.id), include_answers=True)


@router.post("/{assignment_id}/publish")
def publish_assignment(
    assignment_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict:
    item = _teacher_assignment(db, assignment_id, teacher.id)
    if item.status != "draft":
        raise HTTPException(status_code=409, detail="作业已经发布")
    if not db.scalar(select(AssignmentQuestion.id).where(AssignmentQuestion.assignment_id == item.id)):
        raise HTTPException(status_code=400, detail="作业至少需要一道题")
    item.status = "published"
    item.published_at = utcnow()
    item.version += 1
    db.commit()
    return _assignment_payload(item, _load_questions(db, item.id), include_answers=True)


@router.get("")
def list_assignments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    if user.role == "teacher":
        assignments = db.scalars(
            select(Assignment)
            .where(Assignment.teacher_id == user.id)
            .order_by(Assignment.created_at.desc())
        ).all()
        include_answers = True
    else:
        assignments = db.scalars(
            select(Assignment)
            .join(Class, Class.id == Assignment.class_id)
            .join(ClassMembership, ClassMembership.class_id == Assignment.class_id)
            .where(
                ClassMembership.student_id == user.id,
                ClassMembership.status == "active",
                Class.status == "active",
                Assignment.status == "published",
            )
            .order_by(Assignment.created_at.desc())
        ).all()
        include_answers = False
    return [
        _assignment_payload(item, _load_questions(db, item.id), include_answers=include_answers)
        for item in assignments
    ]


@router.get("/{assignment_id}")
def get_assignment(
    assignment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.role == "teacher":
        item = _teacher_assignment(db, assignment_id, user.id)
        include_answers = True
    else:
        item = db.scalar(
            select(Assignment)
            .join(Class, Class.id == Assignment.class_id)
            .join(ClassMembership, ClassMembership.class_id == Assignment.class_id)
            .where(
                Assignment.id == assignment_id,
                Assignment.status == "published",
                ClassMembership.student_id == user.id,
                ClassMembership.status == "active",
                Class.status == "active",
            )
        )
        if not item:
            raise HTTPException(status_code=404, detail="作业不存在")
        include_answers = False
    return _assignment_payload(item, _load_questions(db, item.id), include_answers=include_answers)
