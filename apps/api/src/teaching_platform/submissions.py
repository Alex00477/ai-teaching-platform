from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .assignments import _load_questions
from .auth import require_role
from .db import get_db
from .models import (
    AnswerDraft,
    Assignment,
    Class,
    ClassMembership,
    Submission,
    User,
)

router = APIRouter(prefix="/assignments", tags=["submissions"])


class AnswersRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict, max_length=200)

    @field_validator("answers", mode="before")
    @classmethod
    def clean_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if not isinstance(value, dict):
            raise TypeError("答案格式不正确")
        cleaned: dict[str, str] = {}
        for question_id, answer in value.items():
            if not isinstance(question_id, str) or not question_id.strip():
                raise ValueError("题目编号不正确")
            if not isinstance(answer, str):
                raise TypeError("答案必须是文本")
            cleaned[question_id.strip()] = answer.strip()
        return cleaned


class SubmitRequest(BaseModel):
    answers: dict[str, str] | None = Field(default=None, max_length=200)

    @field_validator("answers", mode="before")
    @classmethod
    def clean_answers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        return AnswersRequest.clean_answers(value)


def _is_due(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= now


def _student_assignment(db: Session, assignment_id: str, student_id: str) -> Assignment:
    item = db.scalar(
        select(Assignment)
        .join(Class, Class.id == Assignment.class_id)
        .join(ClassMembership, ClassMembership.class_id == Assignment.class_id)
        .where(
            Assignment.id == assignment_id,
            Assignment.status == "published",
            Class.status == "active",
            ClassMembership.student_id == student_id,
            ClassMembership.status == "active",
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="作业不存在")
    return item


def _validate_answer_keys(
    answers: dict[str, str], question_ids: set[str], *, require_complete: bool,
) -> None:
    unknown = set(answers) - question_ids
    if unknown:
        raise HTTPException(status_code=400, detail="答案包含无效题目")
    if require_complete:
        missing = question_ids - set(answers)
        if missing:
            raise HTTPException(status_code=400, detail="请完成全部题目后再提交")


def _draft_payload(item: AnswerDraft) -> dict:
    return {
        "draft_id": item.id,
        "assignment_id": item.assignment_id,
        "assignment_version": item.assignment_version,
        "status": "draft",
        "answers": item.answers,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _submission_payload(item: Submission) -> dict:
    return {
        "submission_id": item.id,
        "assignment_id": item.assignment_id,
        "student_id": item.student_id,
        "assignment_version": item.assignment_version,
        "status": item.status,
        "answers": item.answers,
        "submitted_at": item.submitted_at,
    }


@router.get("/{assignment_id}/draft")
def get_draft(
    assignment_id: str,
    student: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> dict:
    assignment = _student_assignment(db, assignment_id, student.id)
    draft = db.scalar(
        select(AnswerDraft).where(
            AnswerDraft.assignment_id == assignment.id,
            AnswerDraft.student_id == student.id,
        )
    )
    if not draft:
        return {
            "draft_id": None,
            "assignment_id": assignment.id,
            "assignment_version": assignment.version,
            "status": "draft",
            "answers": {},
            "created_at": None,
            "updated_at": None,
        }
    if draft.assignment_version != assignment.version:
        raise HTTPException(status_code=409, detail="作业版本已变化，请重新开始作答")
    return _draft_payload(draft)


@router.put("/{assignment_id}/draft")
def save_draft(
    assignment_id: str,
    payload: AnswersRequest,
    student: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> dict:
    assignment = _student_assignment(db, assignment_id, student.id)
    questions = _load_questions(db, assignment.id)
    _validate_answer_keys(payload.answers, {question.id for question in questions}, require_complete=False)

    existing_submission = db.scalar(
        select(Submission.id).where(
            Submission.assignment_id == assignment.id,
            Submission.student_id == student.id,
        )
    )
    if existing_submission:
        raise HTTPException(status_code=409, detail="作业已经提交，不能修改草稿")

    draft = db.scalar(
        select(AnswerDraft)
        .where(AnswerDraft.assignment_id == assignment.id, AnswerDraft.student_id == student.id)
        .with_for_update()
    )
    if draft:
        if draft.assignment_version != assignment.version:
            raise HTTPException(status_code=409, detail="作业版本已变化，请重新开始作答")
        draft.answers = payload.answers
    else:
        draft = AnswerDraft(
            student_id=student.id,
            assignment_id=assignment.id,
            assignment_version=assignment.version,
            answers=payload.answers,
        )
        db.add(draft)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="草稿保存冲突，请重试") from exc
    return _draft_payload(draft)


@router.post("/{assignment_id}/submit", status_code=201)
def submit_assignment(
    assignment_id: str,
    payload: SubmitRequest | None = None,
    student: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> dict:
    assignment = _student_assignment(db, assignment_id, student.id)
    now = datetime.now(UTC)
    if _is_due(assignment.due_at, now):
        raise HTTPException(status_code=409, detail="作业已截止，不能提交")

    existing_submission = db.scalar(
        select(Submission)
        .where(Submission.assignment_id == assignment.id, Submission.student_id == student.id)
        .with_for_update()
    )
    if existing_submission:
        raise HTTPException(status_code=409, detail="作业已经提交")

    questions = _load_questions(db, assignment.id)
    draft = db.scalar(
        select(AnswerDraft)
        .where(AnswerDraft.assignment_id == assignment.id, AnswerDraft.student_id == student.id)
        .with_for_update()
    )
    answers = payload.answers if payload and payload.answers is not None else (draft.answers if draft else {})
    _validate_answer_keys(answers, {question.id for question in questions}, require_complete=True)
    if draft and draft.assignment_version != assignment.version:
        raise HTTPException(status_code=409, detail="作业版本已变化，请重新开始作答")

    submission = Submission(
        student_id=student.id,
        assignment_id=assignment.id,
        assignment_version=assignment.version,
        answers=dict(answers),
        status="submitted",
        submitted_at=now,
    )
    db.add(submission)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="作业已经提交") from exc
    return _submission_payload(submission)


@router.get("/{assignment_id}/submission")
def get_submission(
    assignment_id: str,
    student: User = Depends(require_role("student")),
    db: Session = Depends(get_db),
) -> dict:
    assignment = _student_assignment(db, assignment_id, student.id)
    submission = db.scalar(
        select(Submission).where(
            Submission.assignment_id == assignment.id,
            Submission.student_id == student.id,
        )
    )
    if not submission:
        raise HTTPException(status_code=404, detail="尚未提交作业")
    return _submission_payload(submission)


@router.get("/{assignment_id}/submissions")
def list_submissions(
    assignment_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> list[dict]:
    assignment = db.scalar(
        select(Assignment)
        .join(Class, Class.id == Assignment.class_id)
        .where(
            Assignment.id == assignment_id,
            Assignment.teacher_id == teacher.id,
            Class.teacher_id == teacher.id,
            Class.status == "active",
        )
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="作业不存在")
    submissions = db.scalars(
        select(Submission)
        .where(Submission.assignment_id == assignment.id)
        .order_by(Submission.submitted_at)
    ).all()
    return [_submission_payload(item) for item in submissions]
