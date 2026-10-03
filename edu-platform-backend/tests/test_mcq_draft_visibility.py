"""Unpublished (draft/archived) MCQ papers must not reach students.

The storefront catalog already filtered to published papers, but two other
student paths didn't:
  - the public subject page (/api/mcq-series/{subject}) listed drafts, which
    gave every logged-in student an "Attempt Set" button for them;
  - loading and starting a quiz never checked status, and only checked
    purchase when the paper was flagged is_locked — so an unlocked draft was
    open to anyone signed in, answer key included on submit.

Drafts now hold MCQ editors' unreviewed work, so "draft" has to mean
invisible on the student side. Staff (admin, super_admin, mentor) can still
preview any paper; mcq_editors author in the admin studio and get the
student treatment here.
"""
import pytest


@pytest.fixture
def papers(fake_db):
    fake_db.seed("mcq_papers", [
        {"id": "live", "title": "Live Paper", "level": "FINAL", "subject_code": "FR",
         "status": "published", "is_locked": False, "shuffle_questions": False, "duration_minutes": 60},
        {"id": "draft", "title": "Unreviewed Draft", "level": "FINAL", "subject_code": "FR",
         "status": "draft", "is_locked": False, "shuffle_questions": False, "duration_minutes": 60},
        {"id": "archived", "title": "Retired Paper", "level": "FINAL", "subject_code": "FR",
         "status": "archived", "is_locked": False, "shuffle_questions": False, "duration_minutes": 60},
    ])
    fake_db.seed("exam_sections", [
        {"id": f"sec-{pid}", "paper_id": pid, "title": "Section A", "order_index": 0}
        for pid in ("live", "draft", "archived")
    ])
    fake_db.seed("questions", [
        {"id": f"q-{pid}", "section_id": f"sec-{pid}", "content": "2 + 2?", "options": ["3", "4"],
         "correct_option": 1, "order_index": 0}
        for pid in ("live", "draft", "archived")
    ])
    return fake_db


EDITOR = {"id": "editor-1", "role": "mcq_editor", "email": "editor@example.com"}


def test_public_subject_page_lists_only_published_papers(make_client, papers, student_user):
    res = make_client(student_user).get("/api/mcq-series/FR")
    assert res.status_code == 200
    assert [s["id"] for s in res.json()["sets"]] == ["live"]


@pytest.mark.parametrize("paper_id", ["draft", "archived"])
def test_student_cannot_open_an_unpublished_paper(make_client, papers, student_user, paper_id):
    assert make_client(student_user).get(f"/api/quizzes/{paper_id}").status_code == 404


@pytest.mark.parametrize("paper_id", ["draft", "archived"])
def test_student_cannot_start_an_unpublished_paper(make_client, papers, student_user, paper_id):
    res = make_client(student_user).post(f"/api/quizzes/{paper_id}/attempt/start", json={"questionOrder": [f"q-{paper_id}"]})
    assert res.status_code == 404
    assert papers.table("mcq_attempt_sessions").select("*").execute().data == []


def test_mcq_editor_gets_the_student_treatment_here(make_client, papers):
    assert make_client(EDITOR).get("/api/quizzes/draft").status_code == 404


def test_published_paper_still_opens_and_starts_for_students(make_client, papers, student_user):
    client = make_client(student_user)
    assert client.get("/api/quizzes/live").status_code == 200
    assert client.post("/api/quizzes/live/attempt/start", json={"questionOrder": ["q-live"]}).status_code == 200


@pytest.mark.parametrize("staff", ["admin_user", "mentor_user"])
def test_staff_can_still_preview_a_draft(make_client, papers, staff, request):
    assert make_client(request.getfixturevalue(staff)).get("/api/quizzes/draft").status_code == 200


def test_attempt_started_while_published_can_still_be_submitted_after_archiving(make_client, papers, student_user):
    """Submit is deliberately not gated on status: it already requires an
    attempt started on this same paper, so blocking start is enough to keep
    drafts out — and a student mid-attempt shouldn't lose it because an admin
    archived the paper."""
    client = make_client(student_user)
    start = client.post("/api/quizzes/live/attempt/start", json={"questionOrder": ["q-live"]})
    assert start.status_code == 200
    attempt_id = start.json()["attemptId"]

    papers.table("mcq_papers").update({"status": "archived"}).eq("id", "live").execute()

    res = client.post("/api/quizzes/live/submit-v2", json={
        "attemptId": attempt_id, "answers": {"q-live": 1}, "perQuestionTimes": [5.0], "elapsedSeconds": 5,
    })
    assert res.status_code == 200
