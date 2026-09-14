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
    assert response.status_code == 201
    return response.json()


def test_teacher_creates_class_and_join_code_student_joins_and_teacher_lists_members() -> None:
    client = TestClient(app)
    register(client, "teacher-one", "teacher")
    class_response = client.post("/classes", json={"name": "七年级一班", "subject": "数学"})
    assert class_response.status_code == 201
    class_id = class_response.json()["class_id"]

    code_response = client.post(f"/classes/{class_id}/join-code")
    assert code_response.status_code == 200
    join_code = code_response.json()["join_code"]
    assert join_code.startswith("class-")

    client.post("/auth/logout")
    register(client, "student-one", "student")
    join_response = client.post("/classes/join", json={"join_code": join_code})
    assert join_response.status_code == 200
    assert join_response.json()["class_id"] == class_id
    assert client.get("/classes").json()[0]["name"] == "七年级一班"

    client.post("/auth/logout")
    client.post(
        "/auth/login",
        json={"username": "teacher-one", "password": "a-strong-password-123", "role": "teacher"},
    )
    members = client.get(f"/classes/{class_id}/members")
    assert members.status_code == 200
    assert members.json()[0]["username"] == "student-one"
    assert client.get("/classes").json()[0]["class_id"] == class_id


def test_student_cannot_create_class_or_view_another_teachers_members() -> None:
    client = TestClient(app)
    register(client, "teacher-two", "teacher")
    created = client.post("/classes", json={"name": "八年级二班", "subject": "英语"}).json()
    class_id = created["class_id"]
    client.post("/auth/logout")
    register(client, "student-two", "student")
    assert client.post("/classes", json={"name": "越权班级", "subject": "语文"}).status_code == 403
    assert client.get(f"/classes/{class_id}/members").status_code == 403


def test_student_cannot_join_a_second_class_and_new_code_revokes_old_code() -> None:
    client = TestClient(app)
    register(client, "teacher-three", "teacher")
    first_class = client.post("/classes", json={"name": "九年级一班", "subject": "物理"}).json()
    old_code_response = client.post(f"/classes/{first_class['class_id']}/join-code")
    old_code = old_code_response.json()["join_code"]
    new_code_response = client.post(f"/classes/{first_class['class_id']}/join-code")
    new_code = new_code_response.json()["join_code"]
    assert client.post("/classes/join", json={"join_code": old_code}).status_code == 403

    client.post("/auth/logout")
    register(client, "student-three", "student")
    assert client.post("/classes/join", json={"join_code": new_code}).status_code == 200
    client.post("/auth/logout")
    register(client, "student-four", "student")
    assert client.post("/classes/join", json={"join_code": old_code}).status_code == 400

    client.post("/auth/logout")
    client.post(
        "/auth/login",
        json={"username": "teacher-three", "password": "a-strong-password-123", "role": "teacher"},
    )
    second_class = client.post("/classes", json={"name": "九年级二班", "subject": "物理"}).json()
    second_class_code = client.post(f"/classes/{second_class['class_id']}/join-code").json()["join_code"]
    assert client.delete(f"/classes/{second_class['class_id']}/join-code").status_code == 204
    client.post("/auth/logout")
    register(client, "student-five", "student")
    assert client.post("/classes/join", json={"join_code": second_class_code}).status_code == 400
    client.post("/auth/logout")
    client.post(
        "/auth/login",
        json={"username": "student-three", "password": "a-strong-password-123", "role": "student"},
    )
    assert client.post("/classes/join", json={"join_code": second_class_code}).status_code == 409
