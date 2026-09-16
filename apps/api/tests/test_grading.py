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


def create_submitted_assignment(
    client: TestClient, *, student_username: str, teacher_username: str
) -> tuple[str, str, list[str]]:
    class_id = client.post("/classes", json={"name": "批改班", "subject": "数学"}).json()["class_id"]
    join_code = client.post(f"/classes/{class_id}/join-code").json()["join_code"]
    assignment = client.post(
        "/assignments",
        json={
            "class_id": class_id,
            "title": "批改练习",
            "questions": [
                {"question_type": "choice", "prompt": "1+1?", "options": ["1", "2"]},
                {"question_type": "short", "prompt": "说明理由", "max_score": 5, "rubric": "完整"},
            ],
        },
    )
    assert assignment.status_code == 201, assignment.text
    assignment_id = assignment.json()["assignment_id"]
    assert client.post(f"/assignments/{assignment_id}/publish").status_code == 200

    client.post("/auth/logout")
    register(client, student_username, "student")
    assert client.post("/classes/join", json={"join_code": join_code}).status_code == 200
    questions = client.get(f"/assignments/{assignment_id}").json()["questions"]
    question_ids = [item["question_id"] for item in questions]
    submitted = client.post(
        f"/assignments/{assignment_id}/submit",
        json={"answers": {question_ids[0]: "2", question_ids[1]: "因为加法"}},
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["submission_id"]
    client.post("/auth/logout")
    login(client, teacher_username, "teacher")
    return assignment_id, submission_id, question_ids


def test_teacher_grades_and_confirms_feedback_becomes_visible() -> None:
    client = TestClient(app)
    register(client, "grading-teacher-one", "teacher")
    assignment_id, submission_id, question_ids = create_submitted_assignment(
        client, student_username="grading-student-one", teacher_username="grading-teacher-one"
    )

    listed = client.get(f"/assignments/{assignment_id}/submissions")
    assert listed.status_code == 200
    assert listed.json()[0]["submission_id"] == submission_id
    assert listed.json()[0]["status"] == "submitted"

    partial = client.put(
        f"/submissions/{submission_id}/grading",
        json={
            "items": [{"question_id": question_ids[0], "score": 1, "feedback": "正确"}],
            "confirm": False,
        },
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["status"] == "draft"
    client.post("/auth/logout")
    login(client, "grading-student-one", "student")
    assert client.get(f"/assignments/{assignment_id}/feedback").status_code == 404

    client.post("/auth/logout")
    login(client, "grading-teacher-one", "teacher")
    confirmed = client.put(
        f"/submissions/{submission_id}/grading",
        json={
            "items": [
                {"question_id": question_ids[0], "score": 1, "feedback": "正确"},
                {"question_id": question_ids[1], "score": 3, "feedback": "理由基本完整"},
            ],
            "confirm": True,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["total_score"] == 4
    assert confirmed.json()["max_score"] == 6

    client.post("/auth/logout")
    login(client, "grading-student-one", "student")
    feedback = client.get(f"/assignments/{assignment_id}/feedback")
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["total_score"] == 4
    assert feedback.json()["items"][0]["answer"] == "2"
    assert feedback.json()["items"][1]["is_correct"] is False
    assert "correct_answer" not in feedback.json()["items"][0]
    assert client.get(f"/assignments/{assignment_id}/submission").json()["status"] == "graded"


def test_grading_validates_scope_scores_and_completion() -> None:
    client = TestClient(app)
    register(client, "grading-teacher-two", "teacher")
    assignment_id, submission_id, question_ids = create_submitted_assignment(
        client, student_username="grading-student-two", teacher_username="grading-teacher-two"
    )
    assert client.put(
        f"/submissions/{submission_id}/grading",
        json={
            "items": [
                {"question_id": question_ids[0], "score": 2},
                {"question_id": question_ids[0], "score": 0},
            ],
            "confirm": False,
        },
    ).status_code == 400
    assert client.put(
        f"/submissions/{submission_id}/grading",
        json={"items": [{"question_id": question_ids[1], "score": 6}], "confirm": False},
    ).status_code == 400
    incomplete_confirm = client.put(
        f"/submissions/{submission_id}/grading",
        json={"items": [{"question_id": question_ids[0], "score": 1}], "confirm": True},
    )
    assert incomplete_confirm.status_code == 400

    client.post("/auth/logout")
    register(client, "grading-teacher-three", "teacher")
    assert client.get(f"/submissions/{submission_id}/grading").status_code == 404
    assert client.put(
        f"/submissions/{submission_id}/grading",
        json={"items": [{"question_id": question_ids[0], "score": 1}], "confirm": False},
    ).status_code == 404
    assert client.get(f"/assignments/{assignment_id}/feedback").status_code == 403
