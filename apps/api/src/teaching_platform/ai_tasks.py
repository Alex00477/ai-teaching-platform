from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .grading import _load_context, _question_max_score
from .models import AITask, GradingItem, GradingRecord, Submission
from .ph8 import PH8Client, PH8Error


def claim_next_task(db: Session) -> AITask | None:
    task = db.scalar(
        select(AITask)
        .where(AITask.status == "pending")
        .order_by(AITask.created_at)
        .with_for_update(skip_locked=True)
    )
    if not task:
        return None
    task.status = "processing"
    task.attempts += 1
    task.started_at = datetime.now(UTC)
    db.commit()
    return task


def _fail_task(db: Session, task: AITask, code: str, message: str) -> None:
    task.status = "failed"
    task.error_code = code
    task.error_message = message
    task.completed_at = datetime.now(UTC)
    submission = db.get(Submission, task.submission_id)
    if submission and submission.status == "grading":
        submission.status = "failed"
    db.commit()


def _validate_result(result: dict[str, Any], questions: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = result.get("items")
    if not isinstance(raw_items, list):
        raise PH8Error("invalid_response", "模型结果缺少逐题列表")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise PH8Error("invalid_response", "模型逐题结果格式不正确")
        question_id = raw.get("question_id")
        score = raw.get("score")
        feedback = raw.get("feedback")
        if not isinstance(question_id, str) or question_id not in questions or question_id in seen:
            raise PH8Error("invalid_response", "模型结果题目不匹配")
        if isinstance(score, bool) or not isinstance(score, int):
            raise PH8Error("invalid_response", "模型结果分数格式不正确")
        maximum = _question_max_score(questions[question_id])
        if score < 0 or score > maximum:
            raise PH8Error("invalid_response", "模型结果分数超出范围")
        if feedback is not None and not isinstance(feedback, str):
            raise PH8Error("invalid_response", "模型结果评语格式不正确")
        seen.add(question_id)
        normalized.append({"question_id": question_id, "score": score, "feedback": feedback})
    if seen != set(questions):
        raise PH8Error("invalid_response", "模型结果未覆盖全部题目")
    return normalized


def _build_prompt_questions(questions: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "question_id": question.id,
            "position": question.position,
            "question_type": question.question_type,
            "prompt": question.prompt,
            "options": question.options,
            "correct_answer": question.correct_answer,
            "max_score": _question_max_score(question),
            "rubric": question.rubric,
        }
        for question in sorted(questions.values(), key=lambda item: item.position)
    ]


def process_task(
    db: Session,
    task: AITask,
    *,
    client: PH8Client,
    settings: Settings,
) -> AITask:
    submission = db.get(Submission, task.submission_id)
    if not submission:
        _fail_task(db, task, "submission_missing", "提交不存在")
        return task
    assignment, questions = _load_context(db, submission)
    if submission.assignment_version != task.assignment_version or assignment.version != task.assignment_version:
        _fail_task(db, task, "version_conflict", "提交对应的作业版本已变化")
        return task
    existing = db.scalar(select(GradingRecord).where(GradingRecord.submission_id == submission.id))
    if existing and existing.status == "confirmed":
        _fail_task(db, task, "already_graded", "提交已经存在已确认批改结果")
        return task

    result: dict[str, Any] | None = None
    last_error: PH8Error | None = None
    max_attempts = max(1, settings.worker_max_attempts)
    while task.attempts <= max_attempts:
        try:
            result = client.grade_submission(
                assignment_title=assignment.title,
                questions=_build_prompt_questions(questions),
                answers=submission.answers,
            )
            normalized = _validate_result(result, questions)
            break
        except PH8Error as exc:
            last_error = exc
            if not exc.retryable or task.attempts >= max_attempts:
                _fail_task(db, task, exc.code, exc.message)
                return task
            task.attempts += 1
    else:
        _fail_task(db, task, last_error.code if last_error else "failed", last_error.message if last_error else "批改失败")
        return task

    if result is None:
        _fail_task(db, task, "invalid_response", "模型没有返回结果")
        return task
    record = existing
    if not record:
        record = GradingRecord(
            submission_id=submission.id,
            teacher_id=task.teacher_id,
            assignment_version=task.assignment_version,
            status="draft",
            total_score=0,
            max_score=sum(_question_max_score(question) for question in questions.values()),
        )
        db.add(record)
        db.flush()
    db.execute(delete(GradingItem).where(GradingItem.grading_record_id == record.id))
    total_score = 0
    for item in normalized:
        total_score += item["score"]
        db.add(
            GradingItem(
                grading_record_id=record.id,
                question_id=item["question_id"],
                score=item["score"],
                feedback=item["feedback"],
            )
        )
    record.status = "draft"
    record.assignment_version = task.assignment_version
    record.total_score = total_score
    record.confirmed_at = None
    task.result = {"items": normalized}
    task.status = "pending_review"
    task.error_code = None
    task.error_message = None
    task.completed_at = datetime.now(UTC)
    submission.status = "pending_review"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _fail_task(db, task, "save_conflict", "AI 批改结果保存冲突")
    return task
