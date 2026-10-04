"""Free Resources: per-subject links (Google Drive folders, PDFs, ...) shown
on the public /free-resources page and managed by admins.

Subjects come from the MCQ catalog (mcq_subjects), so the page always lists
every subject the storefront sells, grouped by level, even before an admin
has added a link for it. EXTRA_SUBJECTS adds the ones that exist only here:
Foundation papers with no MCQ product, and an "Others" entry per level.
Tables: supabase/free_resources_migration.sql, free_resources_others_migration.sql.
"""
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError as PostgrestAPIError
from pydantic import BaseModel
from supabase import Client

from app.core.database import get_db
from app.dependencies import require_admin

router = APIRouter(prefix="/api/free-resources", tags=["Free Resources"])
admin_router = APIRouter(prefix="/api/admin/free-resources", tags=["Admin — Free Resources"])

# Tab order on the page, matching the MCQ catalog's default of Final first.
LEVEL_ORDER = ("FINAL", "INTERMEDIATE", "FOUNDATION")

# Free-Resources-only subjects, never sold in the MCQ shop. Ids are stable:
# links are stored against them. "first" ones go before the level's MCQ
# subjects (CA Foundation papers 1 and 2), "Others" always goes last.
EXTRA_SUBJECTS: List[dict] = [
    {"id": "free-foundation-accounting", "level": "FOUNDATION", "name": "Accounting", "position": "first"},
    {"id": "free-foundation-laws", "level": "FOUNDATION", "name": "Business Laws", "position": "first"},
    {"id": "free-final-others", "level": "FINAL", "name": "Others", "position": "last"},
    {"id": "free-inter-others", "level": "INTERMEDIATE", "name": "Others", "position": "last"},
    {"id": "free-foundation-others", "level": "FOUNDATION", "name": "Others", "position": "last"},
]
_EXTRA_IDS = {s["id"] for s in EXTRA_SUBJECTS}

# PostgREST's "table not found" codes — the migration hasn't been run yet.
_MISSING_TABLE_CODES = {"PGRST205", "42P01"}

MAX_TITLE = 120
MAX_URL = 2000


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_title(raw: Optional[str]) -> str:
    title = (raw or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Give the link a title.")
    if len(title) > MAX_TITLE:
        raise HTTPException(status_code=400, detail=f"Title must be under {MAX_TITLE} characters.")
    return title


def _clean_url(raw: Optional[str]) -> str:
    """http(s) only. These render as links on a public page, so a
    javascript:/data: URL (or anything without a real host) must be refused
    here — the table's CHECK constraint is the second line of defence."""
    url = (raw or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Paste the link's URL.")
    if len(url) > MAX_URL:
        raise HTTPException(status_code=400, detail="That URL is too long.")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc or " " in url:
        raise HTTPException(status_code=400, detail="Enter a full link starting with https://")
    return url


def _resource_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "subjectId": row["subject_id"],
        "title": row["title"],
        "url": row["url"],
        "sortOrder": row.get("sort_order", 0),
    }


def _sorted(rows: List[dict]) -> List[dict]:
    # created_at breaks ties so equal sort_orders still render in a stable order.
    return sorted(rows, key=lambda r: (r.get("sort_order") or 0, r.get("created_at") or ""))


def _load_resources(db: Client) -> List[dict]:
    return db.table("free_resources").select("*").execute().data or []


def _group_by_level(subjects: List[dict], resources: List[dict], *, include_inactive: bool) -> List[dict]:
    by_subject: Dict[str, List[dict]] = {}
    for row in _sorted(resources):
        by_subject.setdefault(row["subject_id"], []).append(_resource_out(row))

    levels = []
    for level in LEVEL_ORDER:
        extras = [e for e in EXTRA_SUBJECTS if e["level"] == level]
        level_subjects = (
            [e for e in extras if e["position"] == "first"]
            + [
                s for s in subjects
                if (s.get("level") or "").upper() == level and (include_inactive or s.get("is_active", True))
            ]
            + [e for e in extras if e["position"] == "last"]
        )
        levels.append({
            "level": level,
            "subjects": [
                {
                    "id": s["id"],
                    "code": s.get("code", ""),
                    "name": s.get("name", ""),
                    "groupName": s.get("group_name", ""),
                    **({"isActive": bool(s.get("is_active", True))} if include_inactive else {}),
                    "resources": by_subject.get(s["id"], []),
                }
                for s in level_subjects
            ],
        })
    return levels


def _subjects(db: Client) -> List[dict]:
    return db.table("mcq_subjects").select("*").order("sort_order").execute().data or []


def _others_migration_503() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Run supabase/free_resources_others_migration.sql in Supabase to add links here.",
    )


def _table_missing_503() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Free Resources isn't set up yet — run supabase/free_resources_migration.sql in Supabase.",
    )


def _get_resource(db: Client, resource_id: str) -> dict:
    try:
        rows = db.table("free_resources").select("*").eq("id", resource_id).execute().data or []
    except PostgrestAPIError as e:
        if e.code == "22P02":  # not a UUID, so it can't be any row
            raise HTTPException(status_code=404, detail="Link not found")
        if e.code in _MISSING_TABLE_CODES:
            raise _table_missing_503()
        raise
    if not rows:
        raise HTTPException(status_code=404, detail="Link not found")
    return rows[0]


# ─── Public ───────────────────────────────────────────────────────────────────

@router.get("")
async def list_free_resources(db: Client = Depends(get_db)):
    """Every active MCQ subject by level, each with its links (possibly none)."""
    try:
        resources = _load_resources(db)
    except PostgrestAPIError as e:
        if e.code not in _MISSING_TABLE_CODES:
            raise
        # Before the migration runs, show the subjects with no links rather
        # than breaking the page.
        print("[FREE RESOURCES] free_resources table missing — run free_resources_migration.sql")
        resources = []
    return {"levels": _group_by_level(_subjects(db), resources, include_inactive=False)}


# ─── Admin ────────────────────────────────────────────────────────────────────

class ResourceCreate(BaseModel):
    subjectId: str
    title: str
    url: str


class ResourceUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None


class ResourceMove(BaseModel):
    direction: Literal["up", "down"]


@admin_router.get("")
async def admin_list_free_resources(admin: dict = Depends(require_admin), db: Client = Depends(get_db)):
    """Same shape as the public list, but including inactive subjects (flagged)
    so links can be prepared before a subject goes live."""
    try:
        resources = _load_resources(db)
    except PostgrestAPIError as e:
        if e.code in _MISSING_TABLE_CODES:
            raise _table_missing_503()
        raise
    return {"levels": _group_by_level(_subjects(db), resources, include_inactive=True)}


@admin_router.post("")
async def admin_create_free_resource(
    body: ResourceCreate, admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    title = _clean_title(body.title)
    url = _clean_url(body.url)
    if body.subjectId not in _EXTRA_IDS:
        subject = db.table("mcq_subjects").select("id").eq("id", body.subjectId).execute().data or []
        if not subject:
            raise HTTPException(status_code=400, detail="Unknown subject.")
    try:
        existing = db.table("free_resources").select("sort_order").eq("subject_id", body.subjectId).execute().data or []
        # New links go to the bottom of the subject's list.
        next_order = max((r.get("sort_order") or 0 for r in existing), default=-1) + 1
        res = db.table("free_resources").insert({
            "subject_id": body.subjectId,
            "title": title,
            "url": url,
            "sort_order": next_order,
            "created_by": admin["id"],
        }).execute()
    except PostgrestAPIError as e:
        if e.code in _MISSING_TABLE_CODES:
            raise _table_missing_503()
        # Foreign-key violation: the old link to mcq_subjects is still in place.
        if e.code == "23503" and body.subjectId in _EXTRA_IDS:
            raise _others_migration_503()
        raise
    return _resource_out(res.data[0])


@admin_router.patch("/{resource_id}")
async def admin_update_free_resource(
    resource_id: str, body: ResourceUpdate, admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    _get_resource(db, resource_id)
    changes: dict = {}
    if body.title is not None:
        changes["title"] = _clean_title(body.title)
    if body.url is not None:
        changes["url"] = _clean_url(body.url)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = db.table("free_resources").update(changes).eq("id", resource_id).execute()
    return _resource_out(res.data[0])


@admin_router.post("/{resource_id}/move")
async def admin_move_free_resource(
    resource_id: str, body: ResourceMove, admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    """Swap a link with its neighbour within the same subject. Positions are
    renumbered 0..n-1 first, so duplicate or gapped sort_orders (e.g. from
    manual SQL edits) can't make a move silently do nothing."""
    row = _get_resource(db, resource_id)
    siblings = _sorted(db.table("free_resources").select("*").eq("subject_id", row["subject_id"]).execute().data or [])
    ids = [s["id"] for s in siblings]
    i = ids.index(resource_id)
    j = i - 1 if body.direction == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
    now = datetime.now(timezone.utc).isoformat()
    current = {s["id"]: s.get("sort_order") for s in siblings}
    for position, sid in enumerate(ids):
        if current[sid] != position:
            db.table("free_resources").update({"sort_order": position, "updated_at": now}).eq("id", sid).execute()
    return {"success": True, "order": ids}


@admin_router.delete("/{resource_id}")
async def admin_delete_free_resource(
    resource_id: str, admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    _get_resource(db, resource_id)
    db.table("free_resources").delete().eq("id", resource_id).execute()
    return {"success": True}
