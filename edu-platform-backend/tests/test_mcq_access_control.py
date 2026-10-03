"""Access control on submission: submit-v2 must enforce the same paid/locked
entitlement check get_quiz already applies at retrieval — a student must not
be able to call submit-v2 directly on a locked, unpurchased paper and get the
answer key back in the response.
"""
from datetime import datetime, timezone


def _seed_attempt(fake_db, attempt_id, user_id, set_id):
    """submit-v2 requires a real, persisted attempt session — without one it
    used to grade whatever answers were posted with no ownership/deadline
    check at all (the answer-key-harvesting bug this schema change closed)."""
    fake_db.seed("mcq_attempt_sessions", [{
        "id": attempt_id, "user_id": user_id, "set_id": set_id, "status": "in_progress",
        "question_order": [], "answers": {}, "per_question_times": [],
        "started_at": datetime.now(timezone.utc).isoformat(), "duration_minutes": 60,
    }])


def _seed_locked_paper(fake_db, paper_id="paper-locked"):
    fake_db.seed("mcq_papers", [{
        "id": paper_id, "title": "Locked Paper", "level": "FINAL", "status": "published",
        "subject_code": "FR", "is_locked": True, "shuffle_questions": False,
        "passing_marks": 40.0,
    }])
    fake_db.seed("exam_sections", [{"id": "sec-1", "paper_id": paper_id, "title": "Section A", "order_index": 0}])
    fake_db.seed("questions", [{
        "id": "q1", "section_id": "sec-1", "type": "normal", "case_narrative": "",
        "case_group_id": None, "chapter_tag": "General", "difficulty": "medium",
        "marks": 1.0, "negative_marks": 0.0, "content": "Q1",
        "options": ["a", "b"], "correct_option": 0, "explanation": "", "order_index": 0,
    }])
    fake_db.seed("mcq_subjects", [{"id": "storefront-fr", "code": "FR", "level": "FINAL"}])


def test_submit_v2_blocks_unentitled_student(make_client, fake_db, student_user):
    _seed_locked_paper(fake_db)
    client = make_client(student_user)  # no mcq_enrollments row seeded

    res = client.post("/api/quizzes/paper-locked/submit-v2", json={
        "answers": {"q1": 0}, "perQuestionTimes": [1], "elapsedSeconds": 1,
        "attemptId": "att-1",
    })
    assert res.status_code == 403
    # Must not leak the answer key alongside the rejection.
    assert "questionAnalysis" not in res.json()


def test_get_quiz_blocks_unentitled_student_same_as_submit(make_client, fake_db, student_user):
    _seed_locked_paper(fake_db)
    client = make_client(student_user)

    res = client.get("/api/quizzes/paper-locked")
    assert res.status_code == 403


def test_submit_v2_allows_enrolled_student(make_client, fake_db, student_user):
    _seed_locked_paper(fake_db)
    fake_db.seed("mcq_enrollments", [{
        "user_id": student_user["id"], "subject_code": "storefront-fr", "access_until": None,
    }])
    _seed_attempt(fake_db, "att-1", student_user["id"], "paper-locked")
    client = make_client(student_user)

    res = client.post("/api/quizzes/paper-locked/submit-v2", json={
        "answers": {"q1": 0}, "perQuestionTimes": [1], "elapsedSeconds": 1,
        "attemptId": "att-1",
    })
    assert res.status_code == 200
    assert res.json()["correctCount"] == 1


def test_submit_v2_allows_admin_without_enrollment(make_client, fake_db, admin_user):
    _seed_locked_paper(fake_db)
    _seed_attempt(fake_db, "att-1", admin_user["id"], "paper-locked")
    client = make_client(admin_user)  # no mcq_enrollments row for the admin either

    res = client.post("/api/quizzes/paper-locked/submit-v2", json={
        "answers": {"q1": 0}, "perQuestionTimes": [1], "elapsedSeconds": 1,
        "attemptId": "att-1",
    })
    assert res.status_code == 200
