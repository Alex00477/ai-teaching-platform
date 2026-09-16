from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_role
from .db import get_db
from .models import (
    Assignment,
    AssignmentQuestion,
    Class,
    ClassMembership,
    GradingItem,
    GradingRecord,
    Submission,
    User,
)

router = APIRouter(tags=["grading"])


class GradingItemRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=36)
    score: int = Field(ge=0)
    feedback: str | None = Field(default=None, max_length=10000)

    @field_validator("question_id", mode="before")
    @classmethod
    def strip_question_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("feedback", mode="before")
    @classmethod
    def strip_feedback(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class GradeSubmissionRequest(BaseModel):
    items: list[GradingItemRequest] = Field(min_length=1, max_length=200)
    confirm: bool = False


def _teacher_submission(db: Session, submission_id: str, teacher_id: str) -> Submission:
    item = db.scalar(
        select(Submission)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Class, Class.id == Assignment.class_id)
        .where(
            Submission.id == submission_id,
            Assignment.teacher_id == teacher_id,
            Class.teacher_id == teacher_id,
            Class.status == "active",
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="提交不存在")
    return item


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


def _question_max_score(question: AssignmentQuestion) -> int:
    return question.max_score if question.question_type == "short" else 1


def _record_items(db: Session, record_id: str) -> list[GradingItem]:
    return db.scalars(
        select(GradingItem)
        .join(AssignmentQuestion, AssignmentQuestion.id == GradingItem.question_id)
        .where(GradingItem.grading_record_id == record_id)
        .order_by(AssignmentQuestion.position)
    ).all()


def _record_payload(
    record: GradingRecord,
    items: list[GradingItem],
    questions: dict[str, AssignmentQuestion],
    answers: dict[str, str],
    *,
    include_answers: bool,
) -> dict:
    item_payloads = []
    for item in items:
        question = questions[item.question_id]
        maximum = _question_max_score(question)
        payload = {
            "question_id": item.question_id,
            "position": question.position,
            "question_type": question.question_type,
            "prompt": question.prompt,
            "score": item.score,
            "max_score": maximum,
            "is_correct": item.score == maximum,
            "feedback": item.feedback,
        }
        if include_answers:
            payload["answer"] = answers.get(item.question_id)
        item_payloads.append(payload)
    return {
        "grading_id": record.id,
        "submission_id": record.submission_id,
        "assignment_version": record.assignment_version,
        "status": record.status,
        "total_score": record.total_score,
        "max_score": record.max_score,
        "confirmed_at": record.confirmed_at,
        "items": item_payloads,
    }


def _load_context(db: Session, submission: Submission) -> tuple[Assignment, dict[str, AssignmentQuestion]]:
    assignment = db.get(Assignment, submission.assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="作业不存在")
    questions = db.scalars(
        select(AssignmentQuestion).where(AssignmentQuestion.assignment_id == assignment.id)
    ).all()
    return assignment, {question.id: question for question in questions}


@router.put("/submissions/{submission_id}/grading")
def grade_submission(
    submission_id: str,
    payload: GradeSubmissionRequest,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict:
    submission = _teacher_submission(db, submission_id, teacher.id)
    if submission.status not in {"submitted", "graded", "failed"}:
        raise HTTPException(status_code=409, detail="当前提交状态不能批改")
    assignment, questions = _load_context(db, submission)
    if submission.assignment_version != assignment.version:
        raise HTTPException(status_code=409, detail="提交对应的作业版本已变化")

    request_by_question: dict[str, GradingItemRequest] = {}
    for item in payload.items:
        if item.question_id in request_by_question:
            raise HTTPException(status_code=400, detail="不能重复批改同一道题")
        question = questions.get(item.question_id)
        if not question:
            raise HTTPException(status_code=400, detail="批改包含无效题目")
        maximum = _question_max_score(question)
        if item.score > maximum:
            raise HTTPException(status_code=400, detail="分数超过题目满分")
        request_by_question[item.question_id] = item
    question_ids = set(questions)
    if payload.confirm and set(request_by_question) != question_ids:
        raise HTTPException(status_code=400, detail="确认前必须完成全部题目批改")

    record = db.scalar(
        select(GradingRecord)
        .where(GradingRecord.submission_id == submission.id)
        .with_for_update()
    )
    if record and record.status == "confirmed":
        raise HTTPException(status_code=409, detail="批改结果已经确认")
    if not record:
        record = GradingRecord(
            submission_id=submission.id,
            teacher_id=teacher.id,
            assignment_version=submission.assignment_version,
            status="draft",
            total_score=0,
            max_score=sum(_question_max_score(question) for question in questions.values()),
        )
        db.add(record)
        db.flush()
    elif record.teacher_id != teacher.id or record.assignment_version != submission.assignment_version:
        raise HTTPException(status_code=409, detail="批改版本冲突")

    db.execute(delete(GradingItem).where(GradingItem.grading_record_id == record.id))
    for item in request_by_question.values():
        db.add(
            GradingItem(
                grading_record_id=record.id,
                question_id=item.question_id,
                score=item.score,
                feedback=item.feedback,
            )
        )
    record.total_score = sum(item.score for item in request_by_question.values())
    record.status = "confirmed" if payload.confirm else "draft"
    record.confirmed_at = datetime.now(UTC) if payload.confirm else None
    if payload.confirm:
        submission.status = "graded"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="批改保存冲突，请重试") from exc
    return _record_payload(record, _record_items(db, record.id), questions, submission.answers, include_answers=True)


@router.get("/submissions/{submission_id}/grading")
def get_grading_for_teacher(
    submission_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict:
    submission = _teacher_submission(db, submission_id, teacher.id)
    _assignment, questions = _load_context(db, submission)
    record = db.scalar(select(GradingRecord).where(GradingRecord.submission_id == submission.id))
    if not record:
        raise HTTPException(status_code=404, detail="尚未批改")
    return _record_payload(record, _record_items(db, record.id), questions, submission.answers, include_answers=True)


@router.get("/assignments/{assignment_id}/feedback")
def get_student_feedback(
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
    record = db.scalar(
        select(GradingRecord).where(
            GradingRecord.submission_id == submission.id,
            GradingRecord.status == "confirmed",
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="批改结果尚未确认")
    _, questions = _load_context(db, submission)
    return _record_payload(record, _record_items(db, record.id), questions, submission.answers, include_answers=True)
