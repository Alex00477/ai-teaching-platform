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


def test_teacher_creates_draft_publishes_and_student_visibility_is_scoped() -> None:
    client = TestClient(app)
    register(client, "assignment-teacher-one", "teacher")
    class_item = client.post("/classes", json={"name": "作业班", "subject": "数学"}).json()
    class_id = class_item["class_id"]
    join_code = client.post(f"/classes/{class_id}/join-code").json()["join_code"]

    payload = {
        "class_id": class_id,
        "title": "第一章练习",
        "description": "完成全部题目",
        "questions": [
            {"question_type": "choice", "prompt": "1+1=?", "options": ["1", "2"]},
            {"question_type": "fill", "prompt": "圆周率约等于?"},
            {
                "question_type": "short_answer",
                "prompt": "说明解题思路",
                "max_score": 10,
                "rubric": "步骤完整",
            },
        ],
    }
    created = client.post("/assignments", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"
    assert created.json()["subject"] == "数学"
    assert "correct_answer" in created.json()["questions"][0]

    client.post("/auth/logout")
    register(client, "assignment-student-one", "student")
    assert client.post("/classes/join", json={"join_code": join_code}).status_code == 200
    assert client.get("/assignments").json() == []
    assert client.get(f"/assignments/{created.json()['assignment_id']}").status_code == 404

    client.post("/auth/logout")
    login(client, "assignment-teacher-one", "teacher")
    published = client.post(f"/assignments/{created.json()['assignment_id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert client.post(f"/assignments/{created.json()['assignment_id']}/publish").status_code == 409

    client.post("/auth/logout")
    login(client, "assignment-student-one", "student")
    listed = client.get("/assignments")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["status"] == "published"
    assert "correct_answer" not in listed.json()[0]["questions"][0]


def test_assignment_authorization_and_question_validation() -> None:
    client = TestClient(app)
    register(client, "assignment-teacher-two", "teacher")
    class_id = client.post("/classes", json={"name": "权限班", "subject": "英语"}).json()["class_id"]
    invalid = client.post(
        "/assignments",
        json={
            "class_id": class_id,
            "title": "无效简答题",
            "questions": [{"question_type": "short", "prompt": "缺少评分要点"}],
        },
    )
    assert invalid.status_code == 422

    client.post("/auth/logout")
    register(client, "assignment-teacher-three", "teacher")
    assert client.post(
        "/assignments",
        json={
            "class_id": class_id,
            "title": "越权作业",
            "questions": [{"question_type": "fill", "prompt": "x"}],
        },
    ).status_code == 404
