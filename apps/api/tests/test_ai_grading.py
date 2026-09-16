import httpx
from fastapi.testclient import TestClient
from test_auth import SessionLocal
from test_grading import create_submitted_assignment, login, register

from teaching_platform.ai_tasks import claim_next_task, process_task
from teaching_platform.config import Settings
from teaching_platform.main import app
from teaching_platform.models import AITask, Assignment
from teaching_platform.ph8 import PH8Client


def _settings() -> Settings:
    return Settings(
        session_secret="test-session-secret-012345678901234567890",
        ph8_api_key="test-key",
        ph8_base_url="https://ph8.test/v1",
        ph8_model="deepseek-v4-flash",
        worker_max_attempts=2,
    )


def _run_one_task(handler) -> AITask:
    db = SessionLocal()
    task = claim_next_task(db)
    assert task is not None
    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        settings = _settings()
        process_task(db, task, client=PH8Client(settings, client=client), settings=settings)
        db.refresh(task)
        return task
    finally:
        client.close()
        db.close()


def test_ai_task_is_async_duplicate_safe_and_requires_teacher_confirmation() -> None:
    client = TestClient(app)
    register(client, "ai-teacher-one", "teacher")
    assignment_id, submission_id, question_ids = create_submitted_assignment(
        client, student_username="ai-student-one", teacher_username="ai-teacher-one"
    )
    created = client.post(f"/submissions/{submission_id}/ai-grade")
    task_id = created.json()["task_id"]
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "pending"
    duplicate = client.post(f"/submissions/{submission_id}/ai-grade")
    assert duplicate.status_code == 202
    assert duplicate.json()["task_id"] == task_id

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"items":['
                                f'{{"question_id":"{question_ids[0]}","score":1,"feedback":"正确"}},'
                                f'{{"question_id":"{question_ids[1]}","score":4,"feedback":"不错"}}]}}'
                            )
                        }
                    }
                ]
            },
        )

    task = _run_one_task(handler)
    assert task.id == task_id
    assert task.status == "pending_review"
    status = client.get(f"/ai-grade-tasks/{task_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "pending_review"
    preview = client.get(f"/ai-grade-tasks/{task_id}/preview")
    assert preview.status_code == 200
    assert preview.json()["total_score"] == 5

    client.post("/auth/logout")
    login(client, "ai-student-one", "student")
    assert client.get(f"/assignments/{assignment_id}/feedback").status_code == 404
    client.post("/auth/logout")
    login(client, "ai-teacher-one", "teacher")

    confirmed = client.post(f"/ai-grade-tasks/{task_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert client.post(f"/ai-grade-tasks/{task_id}/confirm").status_code == 409
    client.post("/auth/logout")
    login(client, "ai-student-one", "student")
    feedback = client.get(f"/assignments/{assignment_id}/feedback")
    assert feedback.status_code == 200
    assert feedback.json()["total_score"] == 5


def test_ai_failure_preserves_submission_and_allows_retry() -> None:
    client = TestClient(app)
    register(client, "ai-teacher-two", "teacher")
    assignment_id, submission_id, _ = create_submitted_assignment(
        client, student_username="ai-student-two", teacher_username="ai-teacher-two"
    )
    created = client.post(f"/submissions/{submission_id}/ai-grade")
    task_id = created.json()["task_id"]

    def failure_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "upstream"})

    task = _run_one_task(failure_handler)
    assert task.id == task_id
    assert task.status == "failed"
    assert task.error_code == "upstream_error"
    client.get(f"/ai-grade-tasks/{task_id}").json()
    client.post("/auth/logout")
    login(client, "ai-teacher-two", "teacher")
    submission = client.get(f"/assignments/{assignment_id}/submissions").json()[0]
    assert submission["status"] == "failed"
    retry = client.post(f"/submissions/{submission_id}/ai-grade")
    assert retry.status_code == 202
    assert retry.json()["task_id"] != task_id


def test_ai_invalid_result_and_version_conflict_are_not_published() -> None:
    client = TestClient(app)
    register(client, "ai-teacher-three", "teacher")
    assignment_id, submission_id, _ = create_submitted_assignment(
        client, student_username="ai-student-three", teacher_username="ai-teacher-three"
    )
    client.post(f"/submissions/{submission_id}/ai-grade")
    def invalid_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"items":[]}'}}]},
        )

    task = _run_one_task(invalid_handler)
    assert task.status == "failed"
    assert task.error_code == "invalid_response"

    client.post("/auth/logout")
    login(client, "ai-teacher-three", "teacher")
    retry = client.post(f"/submissions/{submission_id}/ai-grade")
    assert retry.status_code == 202
    retry_id = retry.json()["task_id"]
    db = SessionLocal()
    assignment = db.get(Assignment, assignment_id)
    assert assignment is not None
    assignment.version += 1
    db.commit()
    db.close()
    version_task = _run_one_task(invalid_handler)
    assert version_task.id == retry_id
    assert version_task.status == "failed"
    assert version_task.error_code == "version_conflict"


def test_ai_task_does_not_overwrite_manual_grading_draft() -> None:
    client = TestClient(app)
    register(client, "ai-teacher-four", "teacher")
    _assignment_id, submission_id, question_ids = create_submitted_assignment(
        client, student_username="ai-student-four", teacher_username="ai-teacher-four"
    )
    manual_draft = client.put(
        f"/submissions/{submission_id}/grading",
        json={"items": [{"question_id": question_ids[0], "score": 1}], "confirm": False},
    )
    assert manual_draft.status_code == 200, manual_draft.text
    assert client.post(f"/submissions/{submission_id}/ai-grade").status_code == 409
