"""mcq_editor role: an account that can author MCQ papers and nothing else.

Covers the three things the role must guarantee:
  1. Isolation — every non-MCQ admin endpoint still refuses it (users,
     payments, publishing, self-promotion, mentor-only screens).
  2. Ownership — it only ever sees/edits/deletes papers it created, and only
     while they're drafts. Someone else's paper id must never let it read,
     overwrite, or wipe that paper.
  3. Admins are unaffected, and the role is only ever granted directly in
     Supabase — the admin API refuses to set it.

No dependency overrides for require_admin / require_mcq_author here (unlike
the as_admin/as_mentor shortcuts in conftest): the real role checks run, with
only get_current_user and get_db pointed at test doubles.
"""
import pytest


EDITOR = {"id": "editor-1", "role": "mcq_editor", "email": "editor1@example.com"}
OTHER_EDITOR = {"id": "editor-2", "role": "mcq_editor", "email": "editor2@example.com"}
ADMIN = {"id": "admin-1", "role": "admin", "email": "admin@example.com"}
SUPER_ADMIN = {"id": "super-1", "role": "super_admin", "email": "super@example.com"}
STUDENT = {"id": "student-1", "role": "student", "email": "student@example.com"}


def _paper(pid, created_by=None, status="draft", title=None):
    return {
        "id": pid,
        "title": title or f"Paper {pid}",
        "level": "FINAL",
        "group_name": "GROUP_1",
        "subject_code": "FR",
        "test_type": "FULL_SUBJECT",
        "status": status,
        "created_by": created_by,
        "created_at": "2026-10-01T00:00:00Z",
    }


def _payload(**overrides):
    """A minimal valid POST /mcq-sets body: one section, one question."""
    body = {
        "title": "Editor Paper",
        "level": "FINAL",
        "groupName": "GROUP_1",
        "subjectCode": "FR",
        "testType": "FULL_SUBJECT",
        "status": "draft",
        "sections": [{
            "title": "Section A",
            "questions": [{
                "type": "normal",
                "content": "What is 2 + 2?",
                "options": ["3", "4", "5", "6"],
                "correct_option": 1,
            }],
        }],
    }
    body.update(overrides)
    return body


@pytest.fixture
def seeded(fake_db):
    """One paper for each owner/status combination the rules distinguish,
    each with a question so a wrongful overwrite would be detectable."""
    fake_db.seed("profiles", [
        {"id": EDITOR["id"], "email": EDITOR["email"], "role": "mcq_editor"},
        {"id": OTHER_EDITOR["id"], "email": OTHER_EDITOR["email"], "role": "mcq_editor"},
        {"id": STUDENT["id"], "email": STUDENT["email"], "role": "student"},
    ])
    fake_db.seed("mcq_papers", [
        _paper("own-draft", created_by=EDITOR["id"]),
        _paper("own-published", created_by=EDITOR["id"], status="published"),
        _paper("other-editor-draft", created_by=OTHER_EDITOR["id"]),
        _paper("admin-paper", created_by=None, status="published"),  # every pre-existing paper
    ])
    sections, questions = [], []
    for pid in ("own-draft", "own-published", "other-editor-draft", "admin-paper"):
        sections.append({"id": f"sec-{pid}", "paper_id": pid, "title": "Original", "order_index": 0})
        questions.append({"id": f"q-{pid}", "section_id": f"sec-{pid}", "content": f"original question of {pid}",
                          "options": ["a", "b"], "correct_option": 0, "order_index": 0})
    fake_db.seed("exam_sections", sections)
    fake_db.seed("questions", questions)
    return fake_db


def _paper_row(db, pid):
    rows = [r for r in db.table("mcq_papers").select("*").eq("id", pid).execute().data]
    return rows[0] if rows else None


def _question_contents(db, pid):
    sec_ids = [s["id"] for s in db.table("exam_sections").select("*").eq("paper_id", pid).execute().data]
    if not sec_ids:
        return []
    return [q["content"] for q in db.table("questions").select("*").in_("section_id", sec_ids).execute().data]


# ─── 1. Isolation: everything outside MCQ authoring stays closed ────────────

@pytest.mark.parametrize("method,path", [
    ("get", "/api/admin/users"),
    ("get", "/api/admin/payments"),
    ("get", "/api/admin/summary"),
    ("get", "/api/admin/mcq-series"),
    ("get", "/api/admin/courses"),
    ("get", "/api/admin/my-permissions"),   # mentor-gated
    ("get", "/api/admin/sessions"),         # mentor-gated
])
def test_editor_is_refused_everything_outside_mcq_authoring(make_client, seeded, method, path):
    res = getattr(make_client(EDITOR), method)(path)
    assert res.status_code == 403, f"{method.upper()} {path} -> {res.status_code}"


def test_editor_cannot_publish(make_client, seeded):
    res = make_client(EDITOR).patch("/api/admin/mcq-sets/own-draft/status", json={"status": "published"})
    assert res.status_code == 403
    assert _paper_row(seeded, "own-draft")["status"] == "draft"


def test_editor_cannot_promote_themselves(make_client, seeded):
    res = make_client(EDITOR).patch(f"/api/admin/users/{EDITOR['id']}/role", json={"role": "admin"})
    assert res.status_code == 403
    profile = seeded.table("profiles").select("*").eq("id", EDITOR["id"]).execute().data[0]
    assert profile["role"] == "mcq_editor"


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/admin/mcq-sets", None),
    ("get", "/api/admin/mcq-sets/own-draft", None),
    ("post", "/api/admin/mcq-sets", _payload()),
    ("delete", "/api/admin/mcq-sets/own-draft", None),
])
def test_student_cannot_reach_mcq_authoring(make_client, seeded, method, path, body):
    client = make_client(STUDENT)
    res = client.post(path, json=body) if method == "post" else getattr(client, method)(path)
    assert res.status_code == 403


# ─── 2a. Listing ─────────────────────────────────────────────────────────────

def test_editor_list_contains_only_their_own_papers(make_client, seeded):
    res = make_client(EDITOR).get("/api/admin/mcq-sets")
    assert res.status_code == 200
    assert {p["id"] for p in res.json()} == {"own-draft", "own-published"}


def test_admin_list_shows_everything_and_who_submitted_it(make_client, seeded):
    res = make_client(ADMIN).get("/api/admin/mcq-sets")
    assert res.status_code == 200
    by_id = {p["id"]: p for p in res.json()}
    assert set(by_id) == {"own-draft", "own-published", "other-editor-draft", "admin-paper"}
    assert by_id["own-draft"]["createdByEmail"] == EDITOR["email"]
    assert by_id["other-editor-draft"]["createdByEmail"] == OTHER_EDITOR["email"]
    assert by_id["admin-paper"]["createdByEmail"] is None


# ─── 2b. Creating ────────────────────────────────────────────────────────────

def test_editor_create_is_owned_by_them(make_client, seeded):
    res = make_client(EDITOR).post("/api/admin/mcq-sets", json=_payload(title="Brand new"))
    assert res.status_code == 200
    new_id = res.json()["id"]
    row = _paper_row(seeded, new_id)
    assert row["created_by"] == EDITOR["id"]
    assert row["status"] == "draft"


def test_editor_create_is_forced_to_draft_even_if_body_says_published(make_client, seeded):
    res = make_client(EDITOR).post("/api/admin/mcq-sets", json=_payload(status="published"))
    assert res.status_code == 200
    assert _paper_row(seeded, res.json()["id"])["status"] == "draft"


# ─── 2c. Editing ─────────────────────────────────────────────────────────────

def test_editor_can_edit_own_draft_and_keeps_ownership(make_client, seeded):
    res = make_client(EDITOR).post("/api/admin/mcq-sets", json=_payload(id="own-draft", title="Renamed"))
    assert res.status_code == 200
    row = _paper_row(seeded, "own-draft")
    assert row["title"] == "Renamed"
    assert row["created_by"] == EDITOR["id"]
    assert row["status"] == "draft"
    # And it's still in their list afterwards.
    listed = {p["id"] for p in make_client(EDITOR).get("/api/admin/mcq-sets").json()}
    assert "own-draft" in listed


@pytest.mark.parametrize("target", ["other-editor-draft", "admin-paper"])
def test_editor_cannot_overwrite_someone_elses_paper(make_client, seeded, target):
    """The upsert deletes and re-inserts every section and question of the
    paper id it's given — so this must be refused before any write."""
    before = _paper_row(seeded, target)
    res = make_client(EDITOR).post("/api/admin/mcq-sets", json=_payload(id=target, title="Hijacked"))
    assert res.status_code == 404
    assert _paper_row(seeded, target) == before
    assert _question_contents(seeded, target) == [f"original question of {target}"]


def test_editor_cannot_edit_own_published_paper(make_client, seeded):
    res = make_client(EDITOR).post("/api/admin/mcq-sets", json=_payload(id="own-published", title="Sneaky edit"))
    assert res.status_code == 403
    assert _paper_row(seeded, "own-published")["title"] == "Paper own-published"
    assert _question_contents(seeded, "own-published") == ["original question of own-published"]


def test_editor_cannot_plant_a_paper_under_a_chosen_id(make_client, seeded):
    res = make_client(EDITOR).post("/api/admin/mcq-sets", json=_payload(id="made-up-id"))
    assert res.status_code == 404
    assert _paper_row(seeded, "made-up-id") is None


# ─── 2d. Viewing ─────────────────────────────────────────────────────────────

def test_editor_can_view_own_published_paper(make_client, seeded):
    res = make_client(EDITOR).get("/api/admin/mcq-sets/own-published")
    assert res.status_code == 200
    assert res.json()["id"] == "own-published"


@pytest.mark.parametrize("target", ["other-editor-draft", "admin-paper"])
def test_editor_cannot_view_someone_elses_paper(make_client, seeded, target):
    res = make_client(EDITOR).get(f"/api/admin/mcq-sets/{target}")
    assert res.status_code == 404  # not 403: don't confirm the id exists


# ─── 2e. Deleting ────────────────────────────────────────────────────────────

def test_editor_can_delete_own_draft(make_client, seeded):
    res = make_client(EDITOR).delete("/api/admin/mcq-sets/own-draft")
    assert res.status_code == 200
    assert _paper_row(seeded, "own-draft") is None


@pytest.mark.parametrize("target,expected", [
    ("other-editor-draft", 404),
    ("admin-paper", 404),
    ("own-published", 403),
])
def test_editor_cannot_delete_papers_outside_their_drafts(make_client, seeded, target, expected):
    res = make_client(EDITOR).delete(f"/api/admin/mcq-sets/{target}")
    assert res.status_code == expected
    assert _paper_row(seeded, target) is not None
    assert _question_contents(seeded, target) == [f"original question of {target}"]


# ─── 3. Admins unaffected; role granted only in Supabase ────────────────────

def test_admin_can_still_edit_and_publish_an_editors_draft(make_client, seeded):
    client = make_client(ADMIN)
    assert client.post("/api/admin/mcq-sets", json=_payload(id="own-draft", title="Reviewed")).status_code == 200
    assert client.patch("/api/admin/mcq-sets/own-draft/status", json={"status": "published"}).status_code == 200
    assert _paper_row(seeded, "own-draft")["status"] == "published"


def test_admin_can_still_create_published_papers_directly(make_client, seeded):
    res = make_client(ADMIN).post("/api/admin/mcq-sets", json=_payload(status="published"))
    assert res.status_code == 200
    assert _paper_row(seeded, res.json()["id"])["status"] == "published"


def test_role_api_refuses_mcq_editor_so_it_is_granted_only_in_supabase(make_client, seeded):
    res = make_client(SUPER_ADMIN).patch(f"/api/admin/users/{STUDENT['id']}/role", json={"role": "mcq_editor"})
    assert res.status_code == 400
    profile = seeded.table("profiles").select("*").eq("id", STUDENT["id"]).execute().data[0]
    assert profile["role"] == "student"


def test_editor_gets_404_not_500_for_a_malformed_paper_id():
    """Real Postgres rejects a non-UUID id with 22P02 (the fake DB can't model
    that), which used to surface as an unhandled 500."""
    from fastapi import HTTPException
    from postgrest.exceptions import APIError
    from app.routers.admin import _load_editor_paper

    class _RejectsNonUuid:
        def table(self, _name):
            return self
        def select(self, *_a, **_k):
            return self
        def eq(self, *_a, **_k):
            return self
        def execute(self):
            raise APIError({"code": "22P02", "message": "invalid input syntax for type uuid"})

    with pytest.raises(HTTPException) as exc:
        _load_editor_paper("not-a-uuid", EDITOR, _RejectsNonUuid(), require_draft=True)
    assert exc.value.status_code == 404
