from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from test_auth import make_invite

from teaching_platform.main import app


def register(client: TestClient, username: str, role: str) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "username": username,
            "password": "a-strong-password-123",
            "role": role,
            "invite_code": make_invite(role),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, username: str, role: str) -> None:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": "a-strong-password-123", "role": role},
    )
    assert response.status_code == 200, response.text


def create_published_assignment(client: TestClient, *, due_at: datetime | None = None) -> tuple[str, str]:
    class_id = client.post("/classes", json={"name": "提交班", "subject": "数学"}).json()["class_id"]
    join_code = client.post(f"/classes/{class_id}/join-code").json()["join_code"]
    response = client.post(
        "/assignments",
        json={
            "class_id": class_id,
            "title": "提交练习",
            "due_at": due_at.isoformat() if due_at else None,
            "questions": [
                {"question_type": "choice", "prompt": "1+1?", "options": ["1", "2"]},
                {"question_type": "short", "prompt": "说明理由", "max_score": 5, "rubric": "完整"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    assignment_id = response.json()["assignment_id"]
    assert client.post(f"/assignments/{assignment_id}/publish").status_code == 200
    return assignment_id, join_code


def test_student_saves_draft_recovers_and_submits_immutable_snapshot() -> None:
    client = TestClient(app)
    register(client, "submission-teacher-one", "teacher")
    assignment_id, join_code = create_published_assignment(client)
    client.post("/auth/logout")
    register(client, "submission-student-one", "student")
    assert client.post("/classes/join", json={"join_code": join_code}).status_code == 200

    empty = client.get(f"/assignments/{assignment_id}/draft")
    assert empty.status_code == 200
    assert empty.json()["answers"] == {}
    questions = client.get(f"/assignments/{assignment_id}").json()["questions"]
    first_id, second_id = questions[0]["question_id"], questions[1]["question_id"]

    saved = client.put(
        f"/assignments/{assignment_id}/draft",
        json={"answers": {first_id: "2"}},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["answers"] == {first_id: "2"}
    recovered = client.get(f"/assignments/{assignment_id}/draft")
    assert recovered.json()["answers"] == {first_id: "2"}

    completed = client.put(
        f"/assignments/{assignment_id}/draft",
        json={"answers": {first_id: "2", second_id: "因为加法交换律"}},
    )
    assert completed.status_code == 200
    submitted = client.post(f"/assignments/{assignment_id}/submit")
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["status"] == "submitted"
    submission_id = submitted.json()["submission_id"]
    assert submitted.json()["answers"][second_id] == "因为加法交换律"

    assert client.post(f"/assignments/{assignment_id}/submit").status_code == 409
    assert client.put(
        f"/assignments/{assignment_id}/draft",
        json={"answers": {first_id: "1", second_id: "改动"}},
    ).status_code == 409
    fetched = client.get(f"/assignments/{assignment_id}/submission")
    assert fetched.status_code == 200
    assert fetched.json()["submission_id"] == submission_id
    assert fetched.json()["answers"][first_id] == "2"


def test_submit_rejects_incomplete_unknown_and_late_answers() -> None:
    client = TestClient(app)
    register(client, "submission-teacher-two", "teacher")
    assignment_id, join_code = create_published_assignment(client)
    client.post("/auth/logout")
    register(client, "submission-student-two", "student")
    assert client.post("/classes/join", json={"join_code": join_code}).status_code == 200
    questions = client.get(f"/assignments/{assignment_id}").json()["questions"]
    first_id = questions[0]["question_id"]
    assert client.post(
        f"/assignments/{assignment_id}/submit",
        json={"answers": {first_id: "2"}},
    ).status_code == 400
    assert client.post(
        f"/assignments/{assignment_id}/submit",
        json={"answers": {first_id: "2", "unknown": "x"}},
    ).status_code == 400

    client.post("/auth/logout")
    login(client, "submission-teacher-two", "teacher")
    late_assignment_id, late_code = create_published_assignment(
        client, due_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    client.post("/auth/logout")
    register(client, "submission-student-three", "student")
    assert client.post("/classes/join", json={"join_code": late_code}).status_code == 200
    assert client.post(f"/assignments/{late_assignment_id}/submit").status_code == 409


def test_submission_access_is_scoped_to_membership_and_teacher() -> None:
    client = TestClient(app)
    register(client, "submission-teacher-three", "teacher")
    assignment_id, _join_code = create_published_assignment(client)
    client.post("/auth/logout")
    register(client, "submission-student-four", "student")
    assert client.get(f"/assignments/{assignment_id}/draft").status_code == 404
    assert client.post(f"/assignments/{assignment_id}/submit").status_code == 404
    client.post("/auth/logout")
    login(client, "submission-teacher-three", "teacher")
    assert client.get(f"/assignments/{assignment_id}/submissions").status_code == 200
    assert client.get(f"/assignments/{assignment_id}/draft").status_code == 403
