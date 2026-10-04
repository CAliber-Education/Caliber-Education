"""All India Scholarship Test: paid per paper, one attempt, results hidden
until an admin publishes them, then rank + marks + right/wrong per question.

The real require_admin runs (no as_admin shortcut); only get_current_user and
get_db point at test doubles.
"""
import asyncio
from datetime import datetime, timezone

import pytest

from app.routers import scholarship
from app.routers.payments import _apply_mcq_grant

PAPER = "sch-1"
STUDENT = {"id": "student-1", "role": "student", "email": "s1@example.com"}
STUDENT2 = {"id": "student-2", "role": "student", "email": "s2@example.com"}
ADMIN = {"id": "admin-1", "role": "admin", "email": "admin@example.com"}


def _q(qid, correct, marks=1.0, neg=0.0, order=0):
    return {
        "id": qid, "section_id": "sec-1", "type": "normal", "case_narrative": "", "case_group_id": None,
        "chapter_tag": "General", "difficulty": "medium", "marks": marks, "negative_marks": neg,
        "content": f"Question {qid}", "options": ["a", "b", "c", "d"], "correct_option": correct,
        "explanation": f"Because {qid}", "order_index": order,
    }


@pytest.fixture
def db(fake_db):
    fake_db.seed("mcq_papers", [
        {"id": PAPER, "title": "All India Scholarship Test - CAFC", "level": "FOUNDATION", "subject_code": "SCHOLAR",
         "status": "published", "is_scholarship": True, "is_locked": False, "price": 99.0,
         "allow_retake": True, "duration_minutes": 60, "results_published_at": None, "created_at": "2026-10-01"},
        {"id": "normal-1", "title": "Quant Mock", "level": "FOUNDATION", "subject_code": "QUANT_APT",
         "status": "published", "is_locked": False, "price": 0, "created_at": "2026-10-01"},
        {"id": "sch-draft", "title": "Next year's test", "level": "FOUNDATION", "subject_code": "SCHOLAR",
         "status": "draft", "is_scholarship": True, "price": 99.0, "created_at": "2026-10-02"},
    ])
    fake_db.seed("exam_sections", [{"id": "sec-1", "paper_id": PAPER, "title": "Section A", "order_index": 0}])
    fake_db.seed("questions", [_q("q1", 0, 2.0, 0.5, 0), _q("q2", 1, 2.0, 0.5, 1), _q("q3", 2, 1.0, 0.0, 2)])
    fake_db.seed("profiles", [
        {"id": "student-1", "role": "student", "full_name": "Asha", "email": "s1@example.com", "phone_number": "900"},
        {"id": "student-2", "role": "student", "full_name": "Ravi", "email": "s2@example.com", "phone_number": "901"},
        {"id": "student-3", "role": "student", "full_name": "Meera", "email": "s3@example.com", "phone_number": "902"},
        {"id": "admin-1", "role": "admin", "full_name": "Admin", "email": "admin@example.com"},
    ])
    return fake_db


def _register(db, user_id, paper=PAPER):
    db.seed("mcq_enrollments", [{"user_id": user_id, "subject_code": f"scholarship:{paper}", "level": "SCHOLARSHIP", "access_until": None}])


def _attempt(db, user_id, answers, elapsed, created="2026-10-05T10:00:00Z", paper=PAPER):
    db.seed("quiz_attempts", [{
        "id": f"qa-{user_id}-{created}", "user_id": user_id, "set_id": paper, "score": 0, "total": 5,
        "user_answers": answers, "elapsed_seconds": elapsed, "created_at": created,
    }])


def _take(client, answers):
    start = client.post(f"/api/quizzes/{PAPER}/attempt/start", json={"questionOrder": ["q1", "q2", "q3"]})
    assert start.status_code == 200, start.text
    return client.post(f"/api/quizzes/{PAPER}/submit-v2", json={
        "answers": answers, "perQuestionTimes": [1, 1, 1], "elapsedSeconds": 3,
        "attemptId": start.json()["attemptId"],
    })


# ─── Taking the test ─────────────────────────────────────────────────────────

def test_cannot_open_or_start_without_registering(make_client, db):
    client = make_client(STUDENT)
    assert client.get(f"/api/quizzes/{PAPER}").status_code == 403  # even though is_locked is False
    res = client.post(f"/api/quizzes/{PAPER}/attempt/start", json={"questionOrder": ["q1"]})
    assert res.status_code == 403
    assert "Register" in res.json()["detail"]


def test_submit_hides_marks_answers_and_rank(make_client, db):
    _register(db, STUDENT["id"])
    res = _take(make_client(STUDENT), {"q1": 0, "q2": 3, "q3": None})
    assert res.status_code == 200
    assert res.json() == {"setId": PAPER, "resultPending": True}
    # ...but the attempt is stored for ranking.
    stored = db.store["quiz_attempts"]
    assert len(stored) == 1 and stored[0]["user_answers"] == {"q1": 0, "q2": 3, "q3": None}


def test_only_one_attempt(make_client, db):
    _register(db, STUDENT["id"])
    client = make_client(STUDENT)
    assert _take(client, {"q1": 0}).status_code == 200
    again = client.post(f"/api/quizzes/{PAPER}/attempt/start", json={"questionOrder": ["q1", "q2", "q3"]})
    assert again.status_code == 403
    assert "already taken" in again.json()["detail"]


def test_quiz_leaderboard_is_empty_for_scholarship(make_client, db):
    _attempt(db, "student-2", {"q1": 0}, 100)
    assert make_client(STUDENT).get(f"/api/quizzes/{PAPER}/leaderboard").json() == []


def test_not_listed_inside_subjects(make_client, db):
    client = make_client(STUDENT)
    catalog_ids = [p["id"] for p in client.get("/api/mcq/catalog").json()]
    assert "normal-1" in catalog_ids and PAPER not in catalog_ids
    series = client.get("/api/mcq-series/SCHOLAR").json()
    assert series["sets"] == []


def test_dashboard_attempts_never_include_scholarship_marks(make_client, db):
    _attempt(db, STUDENT["id"], {"q1": 0}, 50)
    db.seed("quiz_attempts", [{"id": "qa-n", "user_id": STUDENT["id"], "set_id": "normal-1", "score": 3, "total": 5, "created_at": "2026-10-04"}])
    me = make_client(STUDENT).get("/api/auth/me").json()
    assert [a["set_id"] for a in me["attempts"]] == ["normal-1"]
    mine = make_client(STUDENT).get("/api/scholarship-tests/my-attempts").json()
    assert mine == [{"paperId": PAPER, "title": "All India Scholarship Test - CAFC",
                     "submittedAt": "2026-10-05T10:00:00Z", "resultsPublished": False}]


# ─── Listing + registration status ───────────────────────────────────────────

def test_public_list_shows_published_scholarship_tests_only(make_client, db):
    tests = make_client(STUDENT).get("/api/scholarship-tests").json()
    assert [t["id"] for t in tests] == [PAPER]
    assert tests[0]["price"] == 99.0 and tests[0]["questionCount"] == 3


def test_my_status(make_client, db):
    client = make_client(STUDENT)
    assert client.get("/api/scholarship-tests/mine").json()[PAPER] == {
        "registered": False, "paymentPending": False, "attempted": False, "resultsPublished": False}
    client.post("/api/payments/submit-manual-scholarship", json={
        "paperId": PAPER, "upiReference": "123456789012", "payerUpiId": "asha@upi", "payerName": "Asha"})
    assert client.get("/api/scholarship-tests/mine").json()[PAPER]["paymentPending"] is True
    _register(db, STUDENT["id"])
    _attempt(db, STUDENT["id"], {}, 10)
    assert client.get("/api/scholarship-tests/mine").json()[PAPER] == {
        "registered": True, "paymentPending": False, "attempted": True, "resultsPublished": False}


# ─── Ranking ─────────────────────────────────────────────────────────────────

def test_rank_by_marks_then_faster_time_and_first_attempt_only(db):
    _attempt(db, "student-1", {"q1": 0, "q2": 1, "q3": 2}, 300)          # 5 marks
    _attempt(db, "student-2", {"q1": 0, "q2": 1, "q3": 0}, 200)          # 4 marks, faster
    _attempt(db, "student-3", {"q1": 0, "q2": 1, "q3": 0}, 250)          # 4 marks, slower
    _attempt(db, "student-3", {"q1": 0, "q2": 1, "q3": 2}, 10, created="2026-10-06T00:00:00Z")  # later retry: ignored
    _attempt(db, "admin-1", {"q1": 0, "q2": 1, "q3": 2}, 1)               # staff: not ranked
    ranking = scholarship.ranked_attempts(db, PAPER)
    assert [(r["userId"], r["rank"], r["score"]) for r in ranking] == [
        ("student-1", 1, 5.0), ("student-2", 2, 4.0), ("student-3", 3, 4.0)]


def test_negative_marking_and_floor_at_zero(db):
    qs = scholarship.paper_questions(db, PAPER)
    assert scholarship.grade(qs, {"q1": 0, "q2": 0})["score"] == 1.5   # +2 - 0.5
    assert scholarship.grade(qs, {"q1": 3, "q2": 0})["score"] == 0.0   # -1 floored


def test_ranking_follows_a_corrected_answer_key(db):
    _attempt(db, "student-1", {"q3": 1}, 10)
    _attempt(db, "student-2", {"q3": 2}, 20)
    assert scholarship.ranked_attempts(db, PAPER)[0]["userId"] == "student-2"
    next(q for q in db.store["questions"] if q["id"] == "q3")["correct_option"] = 1
    assert scholarship.ranked_attempts(db, PAPER)[0]["userId"] == "student-1"


def test_more_attempts_than_one_page(db, monkeypatch):
    monkeypatch.setattr(scholarship, "PAGE", 2)
    for i in range(5):
        db.seed("profiles", [{"id": f"u{i}", "role": "student"}])
        _attempt(db, f"u{i}", {"q1": 0}, 100 + i)
    assert len(scholarship.ranked_attempts(db, PAPER)) == 5


# ─── Admin leaderboard + publishing ──────────────────────────────────────────

def test_admin_leaderboard_has_contacts_and_is_admin_only(make_client, db):
    _attempt(db, "student-1", {"q1": 0}, 10)
    assert make_client(STUDENT).get(f"/api/admin/scholarship-tests/{PAPER}/leaderboard").status_code == 403
    body = make_client(ADMIN).get(f"/api/admin/scholarship-tests/{PAPER}/leaderboard").json()
    row = body["rows"][0]
    assert (row["rank"], row["name"], row["email"], row["phone"], row["score"]) == (1, "Asha", "s1@example.com", "900", 2.0)
    listing = make_client(ADMIN).get("/api/admin/scholarship-tests").json()
    assert {t["id"]: t["attemptCount"] for t in listing} == {PAPER: 1, "sch-draft": 0}


def test_result_hidden_until_published_then_rank_marks_and_answers(make_client, db):
    _attempt(db, "student-1", {"q1": 0, "q2": 0, "q3": None}, 100)   # 2 - 0.5 = 1.5
    _attempt(db, "student-2", {"q1": 0, "q2": 1, "q3": 2}, 300)      # 5
    student = make_client(STUDENT)
    assert student.get(f"/api/scholarship-tests/{PAPER}/my-result").status_code == 403
    assert student.post(f"/api/admin/scholarship-tests/{PAPER}/publish", json={"published": True}).status_code == 403

    assert make_client(ADMIN).post(f"/api/admin/scholarship-tests/{PAPER}/publish", json={"published": True}).status_code == 200
    r = make_client(STUDENT).get(f"/api/scholarship-tests/{PAPER}/my-result").json()
    assert (r["rank"], r["score"], r["totalMarks"]) == (2, 1.5, 5.0)
    assert "totalCompetitors" not in r  # rank only, never "out of"
    assert [(q["id"], q["status"], q["userSelected"], q["correctOptionIndex"]) for q in r["questions"]] == [
        ("q1", "correct", 0, 0), ("q2", "incorrect", 0, 1), ("q3", "skipped", None, 2)]
    assert r["questions"][0]["text"] == "Question q1"

    make_client(ADMIN).post(f"/api/admin/scholarship-tests/{PAPER}/publish", json={"published": False})
    assert make_client(STUDENT).get(f"/api/scholarship-tests/{PAPER}/my-result").status_code == 403


def test_result_for_someone_who_did_not_take_it(make_client, db):
    db.store["mcq_papers"][0]["results_published_at"] = datetime.now(timezone.utc).isoformat()
    assert make_client(STUDENT).get(f"/api/scholarship-tests/{PAPER}/my-result").status_code == 404


# ─── Paying ──────────────────────────────────────────────────────────────────

def test_order_uses_the_paper_price_and_grants_lifetime_access(make_client, db):
    res = make_client(STUDENT).post("/api/payments/create-scholarship-order", json={"paperId": PAPER})
    assert res.status_code == 201, res.text
    assert res.json()["amount"] == 9900
    payment = db.store["payments"][0]
    assert payment["amount"] == 99.0 and payment["utr_number"].startswith(f"mcq-scholarship-lifetime|scholarship:{PAPER}|")

    asyncio.run(_apply_mcq_grant(db, payment["razorpay_order_id"], STUDENT["id"], "pay_x", "sig"))
    assert scholarship.has_access(db, STUDENT["id"], PAPER)
    enrollment = db.store["mcq_enrollments"][0]
    assert enrollment["access_until"] is None and enrollment["level"] == "SCHOLARSHIP"

    again = make_client(STUDENT).post("/api/payments/create-scholarship-order", json={"paperId": PAPER})
    assert again.status_code == 409


def test_cannot_buy_a_draft_or_a_normal_paper(make_client, db):
    client = make_client(STUDENT)
    assert client.post("/api/payments/create-scholarship-order", json={"paperId": "sch-draft"}).status_code == 404
    assert client.post("/api/payments/create-scholarship-order", json={"paperId": "normal-1"}).status_code == 404


def test_manual_upi_registration(make_client, db):
    res = make_client(STUDENT).post("/api/payments/submit-manual-scholarship", json={
        "paperId": PAPER, "upiReference": "123456789012", "payerUpiId": "asha@upi", "payerName": "Asha"})
    assert res.status_code == 201, res.text
    row = db.store["payments"][0]
    assert row["status"] == "pending" and row["payment_method"] == "manual_upi" and row["amount"] == 99.0


# ─── Creating one in the paper editor ────────────────────────────────────────

def _paper_body(**extra):
    return {"title": "AIST", "level": "FOUNDATION", "groupName": "NONE", "subjectCode": "SCHOLAR",
            "status": "draft", "sections": [], **extra}


def test_saving_a_scholarship_paper_sets_one_attempt_and_lock(make_client, db):
    res = make_client(ADMIN).post("/api/admin/mcq-sets", json=_paper_body(id="new-sch", isScholarship=True, price=99))
    assert res.status_code == 200, res.text
    row = next(p for p in db.store["mcq_papers"] if p["id"] == "new-sch")
    assert (row["is_scholarship"], row["is_locked"], row["allow_retake"], row["max_attempts"], row["price"]) == (True, True, False, 1, 99.0)


def test_scholarship_paper_needs_a_price(make_client, db):
    res = make_client(ADMIN).post("/api/admin/mcq-sets", json=_paper_body(id="new-sch", isScholarship=True, price=0))
    assert res.status_code == 400



def test_scholarship_paper_has_no_subject(make_client, db):
    res = make_client(ADMIN).post("/api/admin/mcq-sets", json=_paper_body(id="new-sch", subjectCode="QUANT_APT", isScholarship=True, price=99))
    assert res.status_code == 200, res.text
    assert next(p for p in db.store["mcq_papers"] if p["id"] == "new-sch")["subject_code"] is None


def test_normal_paper_still_needs_a_subject(make_client, db):
    res = make_client(ADMIN).post("/api/admin/mcq-sets", json=_paper_body(id="n1", subjectCode=""))
    assert res.status_code == 400
