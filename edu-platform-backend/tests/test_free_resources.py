"""Free Resources: public per-subject links page + admin management.

The real require_admin runs here (no as_admin shortcut) — only
get_current_user and get_db point at test doubles.
"""
import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.core.database import get_db
from app.main import app
from tests.fake_supabase import FakeSupabaseClient

ADMIN = {"id": "admin-1", "role": "admin", "email": "admin@example.com"}
SUPER_ADMIN = {"id": "super-1", "role": "super_admin", "email": "super@example.com"}
STUDENT = {"id": "student-1", "role": "student", "email": "s@example.com"}
MENTOR = {"id": "mentor-1", "role": "mentor", "email": "m@example.com"}
EDITOR = {"id": "editor-1", "role": "mcq_editor", "email": "e@example.com"}


@pytest.fixture
def seeded(fake_db):
    fake_db.seed("mcq_subjects", [
        {"id": "final-fr", "level": "FINAL", "group_name": "GROUP_1", "code": "FR", "name": "Financial Reporting", "is_active": True, "sort_order": 1},
        {"id": "final-afm", "level": "FINAL", "group_name": "GROUP_1", "code": "AFM", "name": "Advanced Financial Management", "is_active": True, "sort_order": 2},
        {"id": "final-old", "level": "FINAL", "group_name": "GROUP_2", "code": "OLD", "name": "Retired Subject", "is_active": False, "sort_order": 3},
        {"id": "inter-adv-acc", "level": "INTERMEDIATE", "group_name": "GROUP_1", "code": "ADV_ACC", "name": "Advanced Accounting", "is_active": True, "sort_order": 4},
        {"id": "foundation-quant", "level": "FOUNDATION", "group_name": "NONE", "code": "QUANT_APT", "name": "Quantitative Aptitude", "is_active": True, "sort_order": 5},
    ])
    fake_db.seed("free_resources", [
        {"id": "r2", "subject_id": "final-fr", "title": "RTP May 2026", "url": "https://drive.google.com/b", "sort_order": 1, "created_at": "2026-10-01T00:00:00Z"},
        {"id": "r1", "subject_id": "final-fr", "title": "Chapter notes", "url": "https://drive.google.com/a", "sort_order": 0, "created_at": "2026-10-01T00:00:00Z"},
        {"id": "r3", "subject_id": "final-fr", "title": "MTP Series 1", "url": "https://drive.google.com/c", "sort_order": 2, "created_at": "2026-10-01T00:00:00Z"},
    ])
    return fake_db


def _rows(db, subject_id):
    rows = db.table("free_resources").select("*").eq("subject_id", subject_id).execute().data
    return sorted(rows, key=lambda r: r["sort_order"])


# ─── Public page ─────────────────────────────────────────────────────────────

def test_public_needs_no_login(seeded):
    app.dependency_overrides[get_db] = lambda: seeded
    try:
        res = TestClient(app).get("/api/free-resources")  # no Authorization header at all
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200


def test_public_lists_every_active_subject_by_level_even_without_links(make_client, seeded):
    levels = make_client(STUDENT).get("/api/free-resources").json()["levels"]
    assert [l["level"] for l in levels] == ["FINAL", "INTERMEDIATE", "FOUNDATION"]
    by_level = {l["level"]: [s["code"] for s in l["subjects"]] for l in levels}
    assert by_level == {"FINAL": ["FR", "AFM"], "INTERMEDIATE": ["ADV_ACC"], "FOUNDATION": ["QUANT_APT"]}
    afm = levels[0]["subjects"][1]
    assert afm["resources"] == []  # listed even though nothing has been added yet
    assert "isActive" not in afm   # admin-only field


def test_public_links_are_in_order_under_their_subject(make_client, seeded):
    fr = make_client(STUDENT).get("/api/free-resources").json()["levels"][0]["subjects"][0]
    assert [r["title"] for r in fr["resources"]] == ["Chapter notes", "RTP May 2026", "MTP Series 1"]
    assert fr["resources"][0]["url"] == "https://drive.google.com/a"


class _NoFreeResourcesTable(FakeSupabaseClient):
    """The real DB before free_resources_migration.sql has been run."""
    def table(self, name):
        if name == "free_resources":
            class _Missing:
                def __getattr__(self, _attr):
                    return lambda *a, **k: self
                def execute(self):
                    raise APIError({"code": "PGRST205", "message": "Could not find the table 'public.free_resources'"})
            return _Missing()
        return super().table(name)


def test_public_page_still_works_before_the_migration_runs():
    db = _NoFreeResourcesTable()
    db.seed("mcq_subjects", [{"id": "final-fr", "level": "FINAL", "group_name": "GROUP_1", "code": "FR", "name": "Financial Reporting", "is_active": True, "sort_order": 1}])
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        public = client.get("/api/free-resources")
        from app.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: ADMIN
        admin = client.get("/api/admin/free-resources")
    finally:
        app.dependency_overrides.clear()
    assert public.status_code == 200
    assert public.json()["levels"][0]["subjects"][0]["resources"] == []
    # Admins get a clear "run the migration" message instead of a bare 500.
    assert admin.status_code == 503
    assert "free_resources_migration.sql" in admin.json()["detail"]


def test_public_page_shows_links_an_admin_just_added(make_client, seeded):
    make_client(ADMIN).post("/api/admin/free-resources", json={"subjectId": "final-afm", "title": "AFM formulas", "url": "https://drive.google.com/x"})
    afm = make_client(STUDENT).get("/api/free-resources").json()["levels"][0]["subjects"][1]
    assert [r["title"] for r in afm["resources"]] == ["AFM formulas"]


# ─── Admin access ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("user", [STUDENT, MENTOR, EDITOR], ids=["student", "mentor", "mcq_editor"])
@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/admin/free-resources", None),
    ("post", "/api/admin/free-resources", {"subjectId": "final-fr", "title": "x", "url": "https://x.com"}),
    ("patch", "/api/admin/free-resources/r1", {"title": "hijacked"}),
    ("post", "/api/admin/free-resources/r1/move", {"direction": "up"}),
    ("delete", "/api/admin/free-resources/r1", None),
])
def test_only_admins_can_manage_links(make_client, seeded, user, method, path, body):
    client = make_client(user)
    res = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
    assert res.status_code == 403
    assert [r["title"] for r in _rows(seeded, "final-fr")] == ["Chapter notes", "RTP May 2026", "MTP Series 1"]


@pytest.mark.parametrize("user", [ADMIN, SUPER_ADMIN], ids=["admin", "super_admin"])
def test_admin_and_super_admin_can_add_a_link(make_client, seeded, user):
    res = make_client(user).post("/api/admin/free-resources", json={
        "subjectId": "final-afm", "title": "  AFM question bank  ", "url": " https://drive.google.com/drive/folders/abc ",
    })
    assert res.status_code == 200
    row = _rows(seeded, "final-afm")[0]
    assert row["title"] == "AFM question bank"  # trimmed
    assert row["url"] == "https://drive.google.com/drive/folders/abc"
    assert row["created_by"] == user["id"]


def test_new_links_go_to_the_bottom(make_client, seeded):
    make_client(ADMIN).post("/api/admin/free-resources", json={"subjectId": "final-fr", "title": "New one", "url": "https://x.com"})
    assert [r["title"] for r in _rows(seeded, "final-fr")][-1] == "New one"


# ─── Validation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "javascript:alert(document.cookie)",
    "data:text/html,<script>alert(1)</script>",
    "ftp://files.example.com/notes.pdf",
    "drive.google.com/drive/folders/abc",   # no scheme
    "https://",                             # no host
    "https://exa mple.com/x",
    "",
    "https://example.com/" + "a" * 2000,
])
def test_rejects_unsafe_or_malformed_urls(make_client, seeded, url):
    client = make_client(ADMIN)
    created = client.post("/api/admin/free-resources", json={"subjectId": "final-afm", "title": "Notes", "url": url})
    edited = client.patch("/api/admin/free-resources/r1", json={"url": url})
    assert created.status_code == 400
    assert edited.status_code == 400
    assert _rows(seeded, "final-afm") == []
    assert _rows(seeded, "final-fr")[0]["url"] == "https://drive.google.com/a"


@pytest.mark.parametrize("title", ["", "   ", "x" * 121])
def test_rejects_blank_or_overlong_titles(make_client, seeded, title):
    res = make_client(ADMIN).post("/api/admin/free-resources", json={"subjectId": "final-afm", "title": title, "url": "https://x.com"})
    assert res.status_code == 400


def test_rejects_unknown_subject(make_client, seeded):
    res = make_client(ADMIN).post("/api/admin/free-resources", json={"subjectId": "nope", "title": "x", "url": "https://x.com"})
    assert res.status_code == 400


# ─── Edit / reorder / delete ─────────────────────────────────────────────────

def test_admin_can_edit_title_and_url(make_client, seeded):
    res = make_client(ADMIN).patch("/api/admin/free-resources/r1", json={"title": "Notes (updated)", "url": "https://drive.google.com/new"})
    assert res.status_code == 200
    row = [r for r in _rows(seeded, "final-fr") if r["id"] == "r1"][0]
    assert (row["title"], row["url"]) == ("Notes (updated)", "https://drive.google.com/new")


def test_editing_or_deleting_an_unknown_link_is_404(make_client, seeded):
    client = make_client(ADMIN)
    assert client.patch("/api/admin/free-resources/missing", json={"title": "x"}).status_code == 404
    assert client.delete("/api/admin/free-resources/missing").status_code == 404
    assert client.post("/api/admin/free-resources/missing/move", json={"direction": "up"}).status_code == 404


def test_move_reorders_within_the_subject(make_client, seeded):
    client = make_client(ADMIN)
    titles = lambda: [r["title"] for r in _rows(seeded, "final-fr")]
    client.post("/api/admin/free-resources/r3/move", json={"direction": "up"})
    assert titles() == ["Chapter notes", "MTP Series 1", "RTP May 2026"]
    client.post("/api/admin/free-resources/r1/move", json={"direction": "down"})
    assert titles() == ["MTP Series 1", "Chapter notes", "RTP May 2026"]
    # Already at the top: no-op, not an error.
    assert client.post("/api/admin/free-resources/r3/move", json={"direction": "up"}).status_code == 200
    assert titles() == ["MTP Series 1", "Chapter notes", "RTP May 2026"]


def test_move_still_works_when_positions_have_duplicates(make_client, seeded):
    for r in seeded.table("free_resources").select("*").execute().data:
        r["sort_order"] = 0  # e.g. rows added by hand in SQL
    client = make_client(ADMIN)
    before = [r["id"] for r in sorted(_rows(seeded, "final-fr"), key=lambda r: (r["sort_order"], r["created_at"]))]
    client.post(f"/api/admin/free-resources/{before[-1]}/move", json={"direction": "up"})
    after = [r["id"] for r in _rows(seeded, "final-fr")]
    assert after == [before[0], before[2], before[1]]


def test_admin_can_delete_a_link(make_client, seeded):
    assert make_client(ADMIN).delete("/api/admin/free-resources/r2").status_code == 200
    assert [r["id"] for r in _rows(seeded, "final-fr")] == ["r1", "r3"]


def test_admin_list_includes_inactive_subjects_flagged(make_client, seeded):
    final = make_client(ADMIN).get("/api/admin/free-resources").json()["levels"][0]["subjects"]
    flags = {s["code"]: s["isActive"] for s in final}
    assert flags == {"FR": True, "AFM": True, "OLD": False}
