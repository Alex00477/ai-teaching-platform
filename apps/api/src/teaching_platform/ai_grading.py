from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_role
from .db import get_db
from .grading import (
    _load_context,
    _record_items,
    _record_payload,
    _teacher_submission,
)
from .models import AITask, GradingRecord, Submission, User

router = APIRouter(tags=["ai-grading"])


def _task_payload(task: AITask) -> dict:
    return {
        "task_id": task.id,
        "submission_id": task.submission_id,
        "assignment_version": task.assignment_version,
        "status": task.status,
        "attempts": task.attempts,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "result": task.result if task.status in {"pending_review", "confirmed"} else None,
    }


def _teacher_task(db: Session, task_id: str, teacher_id: str) -> AITask:
    task = db.scalar(select(AITask).where(AITask.id == task_id, AITask.teacher_id == teacher_id))
    if not task:
        raise HTTPException(status_code=404, detail="AI 批改任务不存在")
    return task


@router.post("/submissions/{submission_id}/ai-grade", status_code=202)
def create_ai_grade_task(
    submission_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict:
    submission = _teacher_submission(db, submission_id, teacher.id)
    active = db.scalar(
        select(AITask).where(
            AITask.submission_id == submission.id,
            AITask.status.in_(("pending", "processing", "pending_review")),
        )
    )
    if active:
        return _task_payload(active)
    if submission.status == "graded":
        raise HTTPException(status_code=409, detail="提交已经完成批改")
    if submission.status not in {"submitted", "failed"}:
        raise HTTPException(status_code=409, detail="当前提交状态不能发起 AI 批改")
    if db.scalar(select(GradingRecord.id).where(GradingRecord.submission_id == submission.id)):
        raise HTTPException(status_code=409, detail="提交已有人工批改记录，不能发起 AI 批改")
    assignment, _ = _load_context(db, submission)
    if assignment.version != submission.assignment_version:
        raise HTTPException(status_code=409, detail="提交对应的作业版本已变化")
    task = AITask(
        submission_id=submission.id,
        teacher_id=teacher.id,
        assignment_version=submission.assignment_version,
        status="pending",
    )
    db.add(task)
    submission.status = "grading"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        active = db.scalar(
            select(AITask).where(
                AITask.submission_id == submission.id,
                AITask.status.in_(("pending", "processing", "pending_review")),
            )
        )
        if active:
            return _task_payload(active)
        raise HTTPException(status_code=409, detail="AI 批改任务创建冲突，请重试") from exc
    return _task_payload(task)


@router.get("/ai-grade-tasks/{task_id}")
def get_ai_grade_task(
    task_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict:
    return _task_payload(_teacher_task(db, task_id, teacher.id))


@router.post("/ai-grade-tasks/{task_id}/confirm")
def confirm_ai_grade_task(
    task_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict:
    task = _teacher_task(db, task_id, teacher.id)
    if task.status != "pending_review":
        raise HTTPException(status_code=409, detail="AI 批改结果尚未待确认")
    submission = db.get(Submission, task.submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="提交不存在")
    assignment, _questions = _load_context(db, submission)
    if (
        submission.assignment_version != task.assignment_version
        or assignment.version != task.assignment_version
        or submission.status != "pending_review"
    ):
        raise HTTPException(status_code=409, detail="提交版本或状态已变化")
    record = db.scalar(
        select(GradingRecord).where(GradingRecord.submission_id == submission.id).with_for_update()
    )
    if not record or record.assignment_version != task.assignment_version:
        raise HTTPException(status_code=409, detail="AI 批改结果不存在")
    if record.status == "confirmed":
        raise HTTPException(status_code=409, detail="批改结果已经确认")
    record.status = "confirmed"
    record.confirmed_at = datetime.now(UTC)
    task.status = "confirmed"
    task.completed_at = task.completed_at or datetime.now(UTC)
    submission.status = "graded"
    db.commit()
    return _task_payload(task)


@router.get("/ai-grade-tasks/{task_id}/preview")
def preview_ai_grade_task(
    task_id: str,
    teacher: User = Depends(require_role("teacher")),
    db: Session = Depends(get_db),
) -> dict:
    task = _teacher_task(db, task_id, teacher.id)
    if task.status not in {"pending_review", "confirmed"}:
        raise HTTPException(status_code=409, detail="AI 批改结果尚未生成")
    submission = db.get(Submission, task.submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="提交不存在")
    _, questions = _load_context(db, submission)
    record = db.scalar(select(GradingRecord).where(GradingRecord.submission_id == submission.id))
    if not record:
        raise HTTPException(status_code=404, detail="批改结果不存在")
    return _record_payload(record, _record_items(db, record.id), questions, submission.answers, include_answers=True)
