"""Server-persisted MCQ attempt lifecycle: start/resume, order persistence,
ownership checks, and deadline enforcement on the autosave endpoint — all the
building blocks behind "never silently lose progress on refresh" and
"backend is authoritative for the timer".
"""
from datetime import datetime, timedelta, timezone


def _seed_paper(fake_db, paper_id="paper-1", duration_minutes=45, locked=False):
    fake_db.seed("mcq_papers", [{
        "id": paper_id, "title": "Attempt Test", "level": "FINAL", "status": "published",
        "subject_code": "FR", "is_locked": locked, "shuffle_questions": True,
        "duration_minutes": duration_minutes,
    }])


def test_start_creates_attempt_with_duration_snapshotted_from_paper(make_client, fake_db, student_user):
    _seed_paper(fake_db, duration_minutes=45)
    client = make_client(student_user)

    res = client.post("/api/quizzes/paper-1/attempt/start", json={"questionOrder": ["q1", "q2"]})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "started"
    assert body["durationMinutes"] == 45
    assert body["questionOrder"] == ["q1", "q2"]
    assert body["answers"] == {}
    assert body["currentIndex"] == 0
    assert body["attemptId"]


def test_start_resumes_existing_attempt_ignoring_newly_submitted_order(make_client, fake_db, student_user):
    _seed_paper(fake_db)
    client = make_client(student_user)

    first = client.post("/api/quizzes/paper-1/attempt/start", json={"questionOrder": ["q1", "q2"]})
    assert first.status_code == 200
    first_body = first.json()

    second = client.post("/api/quizzes/paper-1/attempt/start", json={"questionOrder": ["q2", "q1"]})
    assert second.status_code == 200
    second_body = second.json()

    assert second_body["status"] == "resumed"
    assert second_body["attemptId"] == first_body["attemptId"]
    # The order from the SECOND call must be ignored — the persisted order
    # from the first call is authoritative.
    assert second_body["questionOrder"] == ["q1", "q2"]


def test_start_returns_400_without_question_order_for_a_fresh_attempt(make_client, fake_db, student_user):
    _seed_paper(fake_db)
    client = make_client(student_user)

    res = client.post("/api/quizzes/paper-1/attempt/start", json={"questionOrder": []})
    assert res.status_code == 400


def test_progress_rejects_a_different_users_attempt(make_client, fake_db, student_user):
    _seed_paper(fake_db)
    client = make_client(student_user)
    start = client.post("/api/quizzes/paper-1/attempt/start", json={"questionOrder": ["q1"]})
    attempt_id = start.json()["attemptId"]

    other_client = make_client({"id": "student-2", "role": "student", "email": "other@example.com"})
    res = other_client.patch(f"/api/quizzes/paper-1/attempt/{attempt_id}/progress", json={
        "answers": {"q1": 0}, "perQuestionTimes": [5], "currentIndex": 0, "sectionElapsed": {}, "elapsedSeconds": 5,
    })
    assert res.status_code == 403


def test_progress_returns_expired_and_does_not_write_past_deadline(make_client, fake_db, student_user):
    started_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    fake_db.seed("mcq_attempt_sessions", [{
        "id": "att-expired", "user_id": student_user["id"], "set_id": "paper-1",
        "status": "in_progress", "question_order": ["q1"], "answers": {"q1": None},
        "per_question_times": [0.0], "current_index": 0, "section_elapsed": {},
        "started_at": started_at, "duration_minutes": 10,
        "last_saved_at": started_at, "submitted_at": None, "submission_id": None,
    }])
    client = make_client(student_user)

    res = client.patch("/api/quizzes/paper-1/attempt/att-expired/progress", json={
        "answers": {"q1": 2}, "perQuestionTimes": [30], "currentIndex": 0, "sectionElapsed": {}, "elapsedSeconds": 3600,
    })
    assert res.status_code == 200
    assert res.json() == {"success": False, "status": "expired"}

    row = fake_db.store["mcq_attempt_sessions"][0]
    assert row["answers"] == {"q1": None}  # untouched — the late write was rejected
