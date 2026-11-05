import re
import sqlite3

from app import create_app


def register(client, name, email, role):
    response = client.post(
        "/register",
        data={
            "name": name,
            "email": email,
            "password": "valid-pass-123",
            "role": role,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200


def test_course_qr_attendance_and_duplicate_prevention(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(tmp_path / "test.sqlite3"),
            "SECRET_KEY": "test-secret",
        }
    )
    teacher = app.test_client()
    register(teacher, "Taylor Teacher", "teacher@example.test", "teacher")
    teacher.post(
        "/courses/create", data={"title": "Algorithms", "subject": "CSE"}
    )
    course_response = teacher.get("/dashboard", follow_redirects=True)
    assert b"Algorithms" in course_response.data

    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    course = db.execute("SELECT id, join_code FROM courses").fetchone()
    course_id, join_code = course["id"], course["join_code"]
    db.close()

    student = app.test_client()
    register(student, "Sam Student", "student@example.test", "student")
    student.post("/courses/join", data={"join_code": join_code})
    teacher.post(f"/courses/{course_id}/sessions", data={"duration": "30"})

    db = sqlite3.connect(app.config["DATABASE"])
    session_row = db.execute("SELECT token FROM attendance_sessions").fetchone()
    db.close()
    attendance_url = f"/attend/{session_row[0]}"

    page = student.get(attendance_url)
    assert page.status_code == 200
    assert b"Confirm attendance" in page.data
    marked = student.post(attendance_url, follow_redirects=True)
    assert b"Attendance recorded." in marked.data
    duplicate = student.post(attendance_url, follow_redirects=True)
    assert b"already recorded" in duplicate.data

    db = sqlite3.connect(app.config["DATABASE"])
    count = db.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
    db.close()
    assert count == 1