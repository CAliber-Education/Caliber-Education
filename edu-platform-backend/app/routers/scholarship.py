"""All India Scholarship Test: a paid, one-attempt MCQ paper whose results
stay hidden until an admin publishes them.

A scholarship test is an ordinary mcq_papers row with is_scholarship = true
(supabase/scholarship_test_migration.sql), taken in the normal quiz screen.
What differs:
  - Access is bought per paper: an mcq_enrollments row with subject_code
    "scholarship:<paper id>" (see access_code), granted by the normal MCQ
    payment flow (payments.py: create-scholarship-order).
  - One attempt per student; submit-v2 stores the attempt but returns no
    marks, answers or rank (mcq.py).
  - Admins see the ranked list here and publish results; only then can a
    student open their own result: rank (no "out of"), marks, and which
    answers were right or wrong.

Ranks and marks are always computed from the stored answers against the
paper's current answer key, so an answer-key correction made before
publishing is reflected everywhere.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError as PostgrestAPIError
from pydantic import BaseModel
from supabase import Client

from app.core.database import get_db
from app.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/scholarship-tests", tags=["Scholarship Test"])
admin_router = APIRouter(prefix="/api/admin/scholarship-tests", tags=["Admin — Scholarship Test"])

ACCESS_PREFIX = "scholarship:"
PAGE = 1000  # PostgREST's default max rows per request
STAFF_ROLES = {"admin", "super_admin", "mentor", "mcq_editor"}

# Postgres "undefined column": the migration hasn't been run yet.
_MISSING_COLUMN_CODES = {"42703", "PGRST204"}


def access_code(paper_id: str) -> str:
    """The mcq_enrollments.subject_code that grants a scholarship paper."""
    return f"{ACCESS_PREFIX}{paper_id}"


def is_scholarship(paper: Optional[dict]) -> bool:
    return bool(paper and paper.get("is_scholarship"))


def migration_missing_503() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="The Scholarship Test isn't set up yet — run supabase/scholarship_test_migration.sql in Supabase.",
    )


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def has_access(db: Client, user_id: str, paper_id: str) -> bool:
    rows = (
        db.table("mcq_enrollments").select("access_until")
        .eq("user_id", user_id).eq("subject_code", access_code(paper_id))
        .execute().data or []
    )
    now = datetime.now(timezone.utc)
    for r in rows:
        until = _parse_dt(r.get("access_until"))
        if until is None or until > now:
            return True
    return False


def _fetch_all(make_query) -> List[dict]:
    """Every row, a page at a time — an All India test can have well over
    the 1,000 rows PostgREST returns per request."""
    rows: List[dict] = []
    start = 0
    while True:
        page = make_query().order("id").range(start, start + PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        start += PAGE


def paper_questions(db: Client, paper_id: str) -> List[dict]:
    """The paper's questions in exam order, with their answer key."""
    sections = db.table("exam_sections").select("*").eq("paper_id", paper_id).execute().data or []
    sections.sort(key=lambda s: s.get("order_index") or 0)
    out: List[dict] = []
    for sec in sections:
        qs = db.table("questions").select("*").eq("section_id", sec["id"]).execute().data or []
        qs.sort(key=lambda q: q.get("order_index") or 0)
        for q in qs:
            out.append({
                "id": q["id"],
                "sectionTitle": sec.get("title") or "",
                "type": q.get("type") or "normal",
                "caseNarrative": q.get("case_narrative") or "",
                "text": q.get("content") or "",
                "options": q.get("options") or [],
                "correctOptionIndex": q.get("correct_option"),
                "marks": float(q.get("marks") or 1.0),
                "negativeMarks": float(q.get("negative_marks") or 0.0),
                "explanation": q.get("explanation") or "",
            })
    return out


def grade(questions: List[dict], answers: Any) -> Dict[str, Any]:
    """Same rules as submit-v2: +marks if right, -negative marks if wrong,
    0 if skipped, total floored at 0. answers: question id -> option index."""
    answers = answers if isinstance(answers, dict) else {}
    score = 0.0
    correct = incorrect = skipped = 0
    rows = []
    for q in questions:
        picked = answers.get(q["id"])
        if not isinstance(picked, int) or isinstance(picked, bool):
            picked = None
        if picked is None:
            status, earned = "skipped", 0.0
            skipped += 1
        elif q["correctOptionIndex"] is not None and picked == int(q["correctOptionIndex"]):
            status, earned = "correct", q["marks"]
            correct += 1
        else:
            status, earned = "incorrect", -q["negativeMarks"]
            incorrect += 1
        score += earned
        rows.append({**q, "userSelected": picked, "status": status, "marksEarned": earned})
    return {
        "score": max(0.0, round(score, 2)),
        "totalMarks": round(sum(q["marks"] for q in questions), 2),
        "correctCount": correct,
        "incorrectCount": incorrect,
        "skippedCount": skipped,
        "questions": rows,
    }


def staff_ids(db: Client, user_ids: List[str]) -> set:
    staff = set()
    for i in range(0, len(user_ids), 200):  # keep each IN (...) list short
        for p in db.table("profiles").select("id, role").in_("id", user_ids[i:i + 200]).execute().data or []:
            if p.get("role") in STAFF_ROLES:
                staff.add(p["id"])
    return staff


def ranked_attempts(db: Client, paper_id: str, questions: Optional[List[dict]] = None,
                    include_staff: bool = False) -> List[dict]:
    """Every student's first attempt, graded and ranked: higher marks first;
    equal marks, the faster time first; then whoever submitted earlier.
    Ranks are 1, 2, 3, ... with no ties.

    Staff (admins, editors, mentors) can take the test to try it out. They're
    never ranked, so they can't push a student down; with include_staff their
    latest attempt is listed after the students, with rank None."""
    questions = questions if questions is not None else paper_questions(db, paper_id)
    attempts = _fetch_all(lambda: db.table("quiz_attempts").select(
        "id, user_id, user_answers, elapsed_seconds, created_at").eq("set_id", paper_id))
    staff = staff_ids(db, list({a["user_id"] for a in attempts}))
    chosen: Dict[str, dict] = {}
    for a in attempts:
        prev = chosen.get(a["user_id"])
        at, prev_at = a.get("created_at") or "", (prev or {}).get("created_at") or ""
        is_staff = a["user_id"] in staff
        # A student's first attempt counts; for staff, their latest try.
        if prev is None or (at > prev_at if is_staff else at < prev_at):
            chosen[a["user_id"]] = a

    def row(a: dict) -> dict:
        g = grade(questions, a.get("user_answers"))
        return {
            "userId": a["user_id"],
            "score": g["score"],
            "totalMarks": g["totalMarks"],
            "correctCount": g["correctCount"],
            "incorrectCount": g["incorrectCount"],
            "skippedCount": g["skippedCount"],
            "timeSeconds": int(a.get("elapsed_seconds") or 0),
            "submittedAt": a.get("created_at"),
            "isStaff": a["user_id"] in staff,
        }

    students = [row(a) for uid, a in chosen.items() if uid not in staff]
    students.sort(key=lambda r: (-r["score"], r["timeSeconds"], r["submittedAt"] or ""))
    for i, r in enumerate(students):
        r["rank"] = i + 1
    if not include_staff:
        return students
    staff_rows = [row(a) for uid, a in chosen.items() if uid in staff]
    staff_rows.sort(key=lambda r: r["submittedAt"] or "", reverse=True)
    for r in staff_rows:
        r["rank"] = None
    return students + staff_rows


def _published_scholarship_papers(db: Client) -> List[dict]:
    try:
        return (
            db.table("mcq_papers").select("*")
            .eq("is_scholarship", True).eq("status", "published")
            .execute().data or []
        )
    except PostgrestAPIError as e:
        if e.code in _MISSING_COLUMN_CODES:
            return []  # before the migration: simply no scholarship tests
        raise


def _load_scholarship_paper(db: Client, paper_id: str) -> dict:
    rows = db.table("mcq_papers").select("*").eq("id", paper_id).execute().data or []
    if not rows or not is_scholarship(rows[0]):
        raise HTTPException(status_code=404, detail="Scholarship test not found")
    return rows[0]


def _question_counts(db: Client, paper_ids: List[str]) -> Dict[str, int]:
    counts = {pid: 0 for pid in paper_ids}
    if not paper_ids:
        return counts
    sections = db.table("exam_sections").select("id, paper_id").in_("paper_id", paper_ids).execute().data or []
    sec_to_paper = {s["id"]: s["paper_id"] for s in sections}
    if sec_to_paper:
        qs = _fetch_all(lambda: db.table("questions").select("id, section_id").in_("section_id", list(sec_to_paper)))
        for q in qs:
            pid = sec_to_paper.get(q["section_id"])
            if pid:
                counts[pid] += 1
    return counts


def _paper_card(p: dict, question_count: int) -> dict:
    return {
        "id": p["id"],
        "title": p.get("title") or "All India Scholarship Test",
        "description": p.get("description") or "",
        "level": p.get("level") or "FOUNDATION",
        "price": float(p.get("price") or 0),
        "durationMinutes": int(p.get("duration_minutes") or 60),
        "totalMarks": float(p.get("total_marks") or 0),
        "questionCount": question_count,
        "resultsPublished": bool(p.get("results_published_at")),
    }


# ─── Students ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_scholarship_tests(db: Client = Depends(get_db)):
    """Published scholarship tests, for the MCQ page. Public."""
    papers = _published_scholarship_papers(db)
    counts = _question_counts(db, [p["id"] for p in papers])
    papers.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return [_paper_card(p, counts[p["id"]]) for p in papers]


@router.get("/mine")
async def my_scholarship_status(current_user: dict = Depends(get_current_user), db: Client = Depends(get_db)):
    """For each published scholarship test: has this student paid, taken it,
    and are results out. Keyed by paper id."""
    papers = _published_scholarship_papers(db)
    # A UPI payment waiting for an admin to confirm it (Admin → Payments).
    pending = db.table("payments").select("utr_number").eq("user_id", current_user["id"]).eq("status", "pending").execute().data or []
    pending_utrs = [p.get("utr_number") or "" for p in pending]
    out: Dict[str, dict] = {}
    for p in papers:
        attempted = bool(
            db.table("quiz_attempts").select("id").eq("set_id", p["id"]).eq("user_id", current_user["id"]).limit(1).execute().data
        )
        registered = has_access(db, current_user["id"], p["id"])
        code = f"|{access_code(p['id'])}|"
        out[p["id"]] = {
            "registered": registered,
            "paymentPending": not registered and any(code in u for u in pending_utrs),
            "attempted": attempted,
            "resultsPublished": bool(p.get("results_published_at")),
        }
    return out


@router.get("/my-attempts")
async def my_attempts(current_user: dict = Depends(get_current_user), db: Client = Depends(get_db)):
    """Scholarship tests this student has taken, for the dashboard: whether
    each result is out yet. No marks here."""
    attempts = (
        db.table("quiz_attempts").select("set_id, created_at")
        .eq("user_id", current_user["id"]).execute().data or []
    )
    first: Dict[str, str] = {}
    for a in attempts:
        sid, at = a.get("set_id"), a.get("created_at") or ""
        if sid and (sid not in first or at < first[sid]):
            first[sid] = at
    if not first:
        return []
    papers = db.table("mcq_papers").select("*").in_("id", list(first)).execute().data or []
    out = [
        {
            "paperId": p["id"],
            "title": p.get("title") or "All India Scholarship Test",
            "submittedAt": first[p["id"]],
            "resultsPublished": bool(p.get("results_published_at")),
        }
        for p in papers if is_scholarship(p)
    ]
    out.sort(key=lambda r: r["submittedAt"], reverse=True)
    return out


@router.get("/{paper_id}/my-result")
async def my_result(paper_id: str, current_user: dict = Depends(get_current_user), db: Client = Depends(get_db)):
    """The student's own result, once published: rank (no "out of"), marks,
    and each question with their answer and the right one."""
    paper = _load_scholarship_paper(db, paper_id)
    if not paper.get("results_published_at"):
        raise HTTPException(status_code=403, detail="Results aren't out yet. You'll see them here once they're published.")
    questions = paper_questions(db, paper_id)
    ranking = ranked_attempts(db, paper_id, questions, include_staff=True)
    mine = next((r for r in ranking if r["userId"] == current_user["id"]), None)
    if mine is None:
        raise HTTPException(status_code=404, detail="You didn't take this test.")
    attempts = (
        db.table("quiz_attempts").select("user_answers, created_at")
        .eq("set_id", paper_id).eq("user_id", current_user["id"]).execute().data or []
    )
    pick = max if mine["isStaff"] else min  # same attempt the leaderboard shows
    graded = grade(questions, pick(attempts, key=lambda a: a.get("created_at") or "").get("user_answers"))
    return {
        "paperId": paper_id,
        "title": paper.get("title") or "All India Scholarship Test",
        "rank": mine["rank"],  # None for a staff test attempt
        "isStaff": mine["isStaff"],
        "score": graded["score"],
        "totalMarks": graded["totalMarks"],
        "correctCount": graded["correctCount"],
        "incorrectCount": graded["incorrectCount"],
        "skippedCount": graded["skippedCount"],
        "timeSeconds": mine["timeSeconds"],
        "publishedAt": paper.get("results_published_at"),
        "questions": graded["questions"],
    }


# ─── Admin ────────────────────────────────────────────────────────────────────

class PublishBody(BaseModel):
    published: bool


@admin_router.get("")
async def admin_list_scholarship_tests(admin: dict = Depends(require_admin), db: Client = Depends(get_db)):
    """Every scholarship paper (drafts too), with how many students took it."""
    try:
        papers = db.table("mcq_papers").select("*").eq("is_scholarship", True).execute().data or []
    except PostgrestAPIError as e:
        if e.code in _MISSING_COLUMN_CODES:
            raise migration_missing_503()
        raise
    counts = _question_counts(db, [p["id"] for p in papers])
    out = []
    for p in sorted(papers, key=lambda p: p.get("created_at") or "", reverse=True):
        takers = {a["user_id"] for a in _fetch_all(
            lambda pid=p["id"]: db.table("quiz_attempts").select("id, user_id").eq("set_id", pid))}
        staff = staff_ids(db, list(takers))
        out.append({
            **_paper_card(p, counts[p["id"]]),
            "status": p.get("status") or "draft",
            "resultsPublishedAt": p.get("results_published_at"),
            "attemptCount": len(takers - staff),
            "staffAttemptCount": len(takers & staff),
        })
    return out


@admin_router.get("/{paper_id}/leaderboard")
async def admin_leaderboard(paper_id: str, admin: dict = Depends(require_admin), db: Client = Depends(get_db)):
    """Everyone who took the test, ranked, with their contact details."""
    paper = _load_scholarship_paper(db, paper_id)
    ranking = ranked_attempts(db, paper_id, include_staff=True)
    ids = [r["userId"] for r in ranking]
    profiles: Dict[str, dict] = {}
    for i in range(0, len(ids), 200):  # keep each IN (...) list short
        chunk = ids[i:i + 200]
        for p in db.table("profiles").select("id, full_name, email, phone_number, stage").in_("id", chunk).execute().data or []:
            profiles[p["id"]] = p
    rows = []
    for r in ranking:
        p = profiles.get(r["userId"], {})
        rows.append({
            **r,
            "name": p.get("full_name") or "",
            "email": p.get("email") or "",
            "phone": p.get("phone_number") or "",
            "stage": p.get("stage") or "",
        })
    return {
        "paper": {
            "id": paper["id"],
            "title": paper.get("title") or "All India Scholarship Test",
            "status": paper.get("status") or "draft",
            "resultsPublishedAt": paper.get("results_published_at"),
        },
        "rows": rows,
    }


@admin_router.post("/{paper_id}/publish")
async def admin_publish_results(
    paper_id: str, body: PublishBody, admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    """Publish (or take back) the results. Students see their result in the
    dashboard only while published."""
    _load_scholarship_paper(db, paper_id)
    value = datetime.now(timezone.utc).isoformat() if body.published else None
    db.table("mcq_papers").update({"results_published_at": value}).eq("id", paper_id).execute()
    return {"success": True, "resultsPublishedAt": value}
