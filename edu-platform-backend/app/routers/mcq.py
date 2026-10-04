import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from supabase import Client
from typing import Optional, List, Dict, Any

from app.core.cache import cached
from app.core.database import get_db
from app.core.limiter import limiter
from app.dependencies import get_current_user
from app.routers import scholarship
from app.schemas.mcq import (
    CalculateMCQPriceRequest,
    CalculateMCQPriceResponse,
    TestSubmissionV2Request,
    SubmissionAnalyticsResponse,
    AttemptStartRequest,
    AttemptProgressRequest,
)

router = APIRouter(tags=["MCQ & Quizzes"])


# ─── Default In-Memory Pricing Matrix & Bundles ─────────────────────────────

DEFAULT_MCQ_SUBJECTS = [
    {'id': 'final-g1-fr', 'level': 'FINAL', 'name': 'FR', 'code': 'FR', 'description': 'Financial Reporting', 'prices': {'1_month': 150, '3_months': 300, '6_months': 400, '1_year': 500}, 'isPopular': True, 'group_name': 'Group I', 'is_active': True, 'sort_order': 1},
    {'id': 'final-g1-afm', 'level': 'FINAL', 'name': 'AFM', 'code': 'AFM', 'description': 'Advanced Financial Management', 'prices': {'1_month': 200, '3_months': 400, '6_months': 500, '1_year': 625}, 'isPopular': False, 'group_name': 'Group I', 'is_active': True, 'sort_order': 1},
    {'id': 'final-g1-audit', 'level': 'FINAL', 'name': 'Audit', 'code': 'Audit', 'description': 'Advanced Auditing & Professional Ethics', 'prices': {'1_month': 150, '3_months': 300, '6_months': 400, '1_year': 500}, 'isPopular': False, 'group_name': 'Group I', 'is_active': True, 'sort_order': 1},
    {'id': 'final-g2-dt', 'level': 'FINAL', 'name': 'DT', 'code': 'DT', 'description': 'Direct Tax Laws', 'prices': {'1_month': 150, '3_months': 300, '6_months': 400, '1_year': 500}, 'isPopular': True, 'group_name': 'Group II', 'is_active': True, 'sort_order': 1},
    {'id': 'final-g2-idt', 'level': 'FINAL', 'name': 'IDT', 'code': 'IDT', 'description': 'Indirect Tax Laws', 'prices': {'1_month': 150, '3_months': 300, '6_months': 400, '1_year': 500}, 'isPopular': False, 'group_name': 'Group II', 'is_active': True, 'sort_order': 1},
    {'id': 'final-g2-case', 'level': 'FINAL', 'name': 'Law+SCMPE+IBS Case Studies', 'code': 'Law+SCMPE+IBS', 'description': 'Integrated Case Studies', 'prices': {'1_month': 200, '3_months': 400, '6_months': 500, '1_year': 625}, 'isPopular': False, 'group_name': 'Group II', 'is_active': True, 'sort_order': 1},
    {'id': 'inter-g1-adv-acc', 'level': 'INTERMEDIATE', 'name': 'Adv Accounting', 'code': 'Adv Accounting', 'description': 'Advanced Accounting', 'prices': {'1_month': 99, '3_months': 200, '6_months': 300, '1_year': 400}, 'isPopular': True, 'group_name': 'Group I', 'is_active': True, 'sort_order': 1},
    {'id': 'inter-g1-corp-law', 'level': 'INTERMEDIATE', 'name': 'Corporate and Other Laws', 'code': 'Corp Laws', 'description': 'Corporate and Other Laws', 'prices': {'1_month': 99, '3_months': 200, '6_months': 300, '1_year': 400}, 'isPopular': False, 'group_name': 'Group I', 'is_active': True, 'sort_order': 1},
    {'id': 'inter-g1-tax', 'level': 'INTERMEDIATE', 'name': 'Taxation', 'code': 'Taxation', 'description': 'Taxation', 'prices': {'1_month': 99, '3_months': 200, '6_months': 300, '1_year': 400}, 'isPopular': False, 'group_name': 'Group I', 'is_active': True, 'sort_order': 1},
    {'id': 'inter-g2-cost', 'level': 'INTERMEDIATE', 'name': 'Cost and Management Accounting', 'code': 'Costing', 'description': 'Cost and Management Accounting', 'prices': {'1_month': 99, '3_months': 200, '6_months': 300, '1_year': 400}, 'isPopular': False, 'group_name': 'Group II', 'is_active': True, 'sort_order': 1},
    {'id': 'inter-g2-audit', 'level': 'INTERMEDIATE', 'name': 'Auditing and Ethics', 'code': 'Audit & Ethics', 'description': 'Auditing and Ethics', 'prices': {'1_month': 99, '3_months': 200, '6_months': 300, '1_year': 400}, 'isPopular': False, 'group_name': 'Group II', 'is_active': True, 'sort_order': 1},
    {'id': 'inter-g2-fm-sm', 'level': 'INTERMEDIATE', 'name': 'Financial Management and Strategic Management', 'code': 'FM & SM', 'description': 'Financial Management and Strategic Management', 'prices': {'1_month': 99, '3_months': 200, '6_months': 300, '1_year': 400}, 'isPopular': False, 'group_name': 'Group II', 'is_active': True, 'sort_order': 1},
    {'id': 'found-quant', 'level': 'FOUNDATIONS', 'name': 'Quantitative Aptitude', 'code': 'Quant', 'description': 'Quantitative Aptitude', 'prices': {'1_month': 200, '3_months': 400, '6_months': 500, '1_year': 625}, 'isPopular': True, 'group_name': 'All', 'is_active': True, 'sort_order': 1},
    {'id': 'found-eco', 'level': 'FOUNDATIONS', 'name': 'Business Economics', 'code': 'Economics', 'description': 'Business Economics', 'prices': {'1_month': 150, '3_months': 300, '6_months': 400, '1_year': 500}, 'isPopular': False, 'group_name': 'All', 'is_active': True, 'sort_order': 1},
]

DEFAULT_MCQ_BUNDLES = [
    {'id': 'final-bundle-g1', 'title': 'Group I - All Subjects', 'level': 'FINAL', 'prices': {'1_month': 450, '3_months': 900, '6_months': 1200, '1_year': 1500}, 'badge': 'Group I', 'group_name': 'Group I', 'subject_ids': ['final-g1-fr', 'final-g1-afm', 'final-g1-audit'], 'is_active': True, 'is_custom': False},
    {'id': 'final-bundle-g2', 'title': 'Group II - All Subjects', 'level': 'FINAL', 'prices': {'1_month': 450, '3_months': 900, '6_months': 1200, '1_year': 1500}, 'badge': 'Group II', 'group_name': 'Group II', 'subject_ids': ['final-g2-dt', 'final-g2-idt', 'final-g2-case'], 'is_active': True, 'is_custom': False},
    {'id': 'final-bundle-both', 'title': 'Both Groups', 'level': 'FINAL', 'prices': {'1_month': 900, '3_months': 1800, '6_months': 2400, '1_year': 3000}, 'badge': 'Super Saver', 'group_name': 'Both Groups', 'subject_ids': ['final-g1-fr', 'final-g1-afm', 'final-g1-audit', 'final-g2-dt', 'final-g2-idt', 'final-g2-case'], 'is_active': True, 'is_custom': False},
    {'id': 'inter-bundle-g1', 'title': 'Group I - All Subjects', 'level': 'INTERMEDIATE', 'prices': {'1_month': 250, '3_months': 500, '6_months': 800, '1_year': 1000}, 'badge': 'Group I', 'group_name': 'Group I', 'subject_ids': ['inter-g1-adv-acc', 'inter-g1-corp-law', 'inter-g1-tax'], 'is_active': True, 'is_custom': False},
    {'id': 'inter-bundle-g2', 'title': 'Group II - All Subjects', 'level': 'INTERMEDIATE', 'prices': {'1_month': 250, '3_months': 500, '6_months': 800, '1_year': 1000}, 'badge': 'Group II', 'group_name': 'Group II', 'subject_ids': ['inter-g2-cost', 'inter-g2-audit', 'inter-g2-fm-sm'], 'is_active': True, 'is_custom': False},
    {'id': 'inter-bundle-both', 'title': 'Both Groups', 'level': 'INTERMEDIATE', 'prices': {'1_month': 500, '3_months': 1000, '6_months': 1600, '1_year': 2000}, 'badge': 'Super Saver', 'group_name': 'Both Groups', 'subject_ids': ['inter-g1-adv-acc', 'inter-g1-corp-law', 'inter-g1-tax', 'inter-g2-cost', 'inter-g2-audit', 'inter-g2-fm-sm'], 'is_active': True, 'is_custom': False},
    {'id': 'found-bundle-all', 'title': 'All Subjects', 'level': 'FOUNDATIONS', 'prices': {'1_month': 300, '3_months': 650, '6_months': 800, '1_year': 1000}, 'badge': 'Complete Bundle', 'group_name': 'All', 'subject_ids': ['found-quant', 'found-eco'], 'is_active': True, 'is_custom': False},
]


def _group_label(group: str) -> str:
    """Display name for a stored group code ("NONE" is Foundation, which has no groups)."""
    return {"GROUP_1": "Group I", "GROUP_2": "Group II", "BOTH": "Both Groups", "NONE": "CA Foundation", "All": "CA Foundation"}.get(group, group)


def _get_active_subjects_and_bundles(db: Client):
    """Fetches subjects and bundles from DB if table exists, otherwise returns defaults.

    Cached for 60s — this pricing/catalog data only changes on an admin edit,
    but was being re-fetched from the DB on every pricing calc / order create
    / catalog load."""
    def fetch():
        try:
            sub_res = db.table("mcq_subjects").select("*").eq("is_active", True).order("sort_order").execute()
            subjects = sub_res.data if sub_res.data else DEFAULT_MCQ_SUBJECTS
        except Exception:
            subjects = DEFAULT_MCQ_SUBJECTS

        try:
            bun_res = db.table("mcq_bundles").select("*").eq("is_active", True).execute()
            bundles = bun_res.data if bun_res.data else DEFAULT_MCQ_BUNDLES
        except Exception:
            bundles = DEFAULT_MCQ_BUNDLES

        return subjects, bundles

    return cached("mcq_subjects_and_bundles", 60, fetch)


def calculate_mcq_cart(level: str, subject_ids: list[str], duration: str, db: Client):
    subjects, bundles = _get_active_subjects_and_bundles(db)
    level_norm = level.upper()
    dur_norm = duration.lower().replace("-", "_").replace(" ", "_")
    if dur_norm not in ["1_month", "3_months", "6_months", "1_year"]:
        dur_norm = "1_month"

    # Map selected subjects
    level_subjects = [s for s in subjects if s["level"].upper() == level_norm]
    sub_map = {s["id"]: s for s in level_subjects}
    selected = [sub_map[sid] for sid in subject_ids if sid in sub_map]

    # Compute base sum
    real_total = sum(float(s["prices"].get(dur_norm, 0)) for s in selected)

    # Check for bundle matches
    selected_set = set(s["id"] for s in selected)
    level_bundles = [b for b in bundles if b["level"].upper() == level_norm and b.get("is_active", True)]

    # Check exact super bundle or matching bundles
    applied_bundle = None
    discounted_price = real_total

    # Find the largest matching bundle subset
    best_bundle = None
    for b in level_bundles:
        bundle_set = set(b.get("subject_ids", []))
        if bundle_set and bundle_set.issubset(selected_set):
            b_price = float(b["prices"].get(dur_norm, 0))
            # Calculate remaining subjects not covered by bundle
            remaining_ids = selected_set - bundle_set
            rem_price = sum(float(sub_map[rid]["prices"].get(dur_norm, 0)) for rid in remaining_ids if rid in sub_map)
            candidate_price = b_price + rem_price

            if candidate_price < discounted_price:
                discounted_price = candidate_price
                best_bundle = b

    if best_bundle and discounted_price < real_total:
        applied_bundle = best_bundle

    savings = max(0.0, real_total - discounted_price)
    savings_pct = round((savings / real_total * 100), 1) if real_total > 0 else 0.0

    # Build smart upsell recommendation if user selected fewer subjects than a full group/bundle
    upsell = None
    if len(selected) > 0 and len(selected) < len(level_subjects):
        # Identify group of selected subjects
        first_sub = selected[0]
        group = first_sub.get("group_name", "Group I")
        group_subjects = [s for s in level_subjects if s.get("group_name") == group or group == "All"]
        group_sub_ids = set(s["id"] for s in group_subjects)

        # If user has not selected the full group, recommend the group bundle
        if not group_sub_ids.issubset(selected_set):
            matching_g_bundle = next((b for b in level_bundles if b.get("group_name") == group), None)
            if matching_g_bundle:
                bundle_price = float(matching_g_bundle["prices"].get(dur_norm, 0))
                full_base_sum = sum(float(s["prices"].get(dur_norm, 0)) for s in group_subjects)
                upsell = {
                    "type": "group_upgrade",
                    "group": group,
                    "bundleId": matching_g_bundle["id"],
                    "bundleTitle": matching_g_bundle["title"],
                    "subjectIds": matching_g_bundle["subject_ids"],
                    "subjectNames": [s["name"] for s in group_subjects],
                    "bundlePrice": bundle_price,
                    "originalSum": full_base_sum,
                    "savings": max(0.0, full_base_sum - bundle_price),
                    "message": f"Get all {_group_label(group)} subjects for just ₹{int(bundle_price)} (Normally ₹{int(full_base_sum)})"
                }
        elif level_norm in ["FINAL", "INTERMEDIATE"] and len(selected_set) < 6:
            # Upsell to Both Groups Super Bundle
            both_bundle = next((b for b in level_bundles if b.get("group_name") == "Both Groups"), None)
            if both_bundle:
                bundle_price = float(both_bundle["prices"].get(dur_norm, 0))
                full_base_sum = sum(float(s["prices"].get(dur_norm, 0)) for s in level_subjects)
                upsell = {
                    "type": "both_groups_upgrade",
                    "group": "Both Groups",
                    "bundleId": both_bundle["id"],
                    "bundleTitle": both_bundle["title"],
                    "subjectIds": both_bundle["subject_ids"],
                    "bundlePrice": bundle_price,
                    "originalSum": full_base_sum,
                    "savings": max(0.0, full_base_sum - bundle_price),
                    "message": f"Upgrade to Both Groups Super Bundle for just ₹{int(bundle_price)} (Normally ₹{int(full_base_sum)})"
                }

    return {
        "level": level_norm,
        "duration": dur_norm,
        "selected_subject_ids": [s["id"] for s in selected],
        "real_total_price": round(real_total, 2),
        "discounted_price": round(discounted_price, 2),
        "savings_amount": round(savings, 2),
        "savings_percentage": savings_pct,
        "applied_bundle_id": applied_bundle["id"] if applied_bundle else None,
        "applied_bundle_title": applied_bundle["title"] if applied_bundle else None,
        "upsell_recommendation": upsell,
    }


# ─── MCQ Packages & Pricing Endpoints ─────────────────────────────────────────

def _format_subject_for_client(s: dict) -> dict:
    group = s.get("group_name") or s.get("groupName") or "All"
    return {
        "id": s.get("id", ""),
        "level": (s.get("level") or "FINAL").upper(),
        "group_name": group,
        "groupName": group,
        "name": s.get("name", ""),
        "code": s.get("code", ""),
        "description": s.get("description", ""),
        "prices": s.get("prices") or {"1_month": 150, "3_months": 300, "6_months": 400, "1_year": 500},
        "is_active": s.get("is_active", True),
        "isActive": s.get("is_active", True),
        "sort_order": s.get("sort_order", 0),
    }

def _format_bundle_for_client(b: dict) -> dict:
    group = b.get("group_name") or b.get("groupName") or "All"
    sub_ids = b.get("subject_ids") or b.get("subjectIds") or []
    return {
        "id": b.get("id", ""),
        "title": b.get("title", ""),
        "level": (b.get("level") or "FINAL").upper(),
        "group_name": group,
        "groupName": group,
        "subject_ids": sub_ids,
        "subjectIds": sub_ids,
        "prices": b.get("prices") or {"1_month": 450, "3_months": 900, "6_months": 1200, "1_year": 1500},
        "badge": b.get("badge") or group,
        "is_custom": b.get("is_custom", False),
        "isCustom": b.get("is_custom", False),
        "is_active": b.get("is_active", True),
        "isActive": b.get("is_active", True),
    }

@router.get("/api/mcq/packages")
async def get_mcq_packages(db: Client = Depends(get_db)):
    """Returns flat subjects catalog and promotional bundles grouped by level."""
    raw_subjects, raw_bundles = _get_active_subjects_and_bundles(db)
    
    subjects = [_format_subject_for_client(s) for s in raw_subjects]
    bundles = [_format_bundle_for_client(b) for b in raw_bundles]
    
    levels = ["FINAL", "INTERMEDIATE", "FOUNDATION"]
    res_levels = {}
    for lvl in levels:
        lvl_subs = [s for s in subjects if s["level"].upper() == lvl]
        lvl_buns = [b for b in bundles if b["level"].upper() == lvl]
        res_levels[lvl] = {
            "subjects": lvl_subs,
            "bundles": lvl_buns,
        }
    
    return {
        "levels": res_levels,
        "allSubjects": subjects,
        "allBundles": bundles,
    }


@router.post("/api/mcq/calculate-price", response_model=CalculateMCQPriceResponse)
async def calculate_price(body: CalculateMCQPriceRequest, db: Client = Depends(get_db)):
    """Calculates real total vs bundle discounted price and returns smart upsells."""
    result = calculate_mcq_cart(body.level, body.subject_ids, body.duration, db)
    return result


# ─── MCQ Series ───────────────────────────────────────────────────────────────

@router.get("/api/mcq-series")
async def list_series(db: Client = Depends(get_db)):
    # Map MCQ Subjects to act like "Series" so the student dashboard renders them automatically
    sub_res = db.table("mcq_subjects").select("*").execute()
    subjects = sub_res.data or []
    series_list = []
    for s in subjects:
        series_list.append({
            "id": s["code"], # Using code as the route ID (e.g., /mcq/FR)
            "title": s["name"],
            "subject": f"{s['level']} • {s.get('group_name', '')}",
            "description": s.get("description", ""),
            "isLocked": False, # Unlock the folder, the tests inside will lock based on purchase
            "is_locked": False, 
        })
    return series_list


@router.get("/api/mcq-series/{series_id}")
async def get_series(series_id: str, db: Client = Depends(get_db)):
    # series_id is actually the subject_code (e.g. FR, AFM)
    subject = db.table("mcq_subjects").select("*").eq("code", series_id).execute()
    if not subject.data:
        # Fallback to returning an empty wrapper if not found but requested
        subject_data = {"id": series_id, "name": series_id, "level": "Subject", "description": ""}
    else:
        subject_data = subject.data[0]

    series_mock = {
        "id": series_id,
        "title": subject_data.get("name", series_id),
        "subject": subject_data.get("level", ""),
        "description": subject_data.get("description", ""),
        "is_locked": False,
        "price": 0
    }

    # Published papers only. This endpoint is public, and listing a draft here
    # also handed every logged-in student an "Attempt Set" button for it —
    # drafts include MCQ editors' unreviewed work, so they must not surface.
    papers = db.table("mcq_papers").select("*").eq("subject_code", series_id).eq("status", "published").execute()
    # Scholarship tests are sold on their own, not inside a subject.
    paper_rows = [p for p in (papers.data or []) if not scholarship.is_scholarship(p)]
    paper_ids = [p["id"] for p in paper_rows]

    # Batched instead of one exam_sections + one questions query per paper —
    # this endpoint was previously issuing 2 extra round trips per paper.
    sections_by_paper: Dict[str, list] = {pid: [] for pid in paper_ids}
    question_count_by_section: Dict[str, int] = {}
    if paper_ids:
        all_sections = db.table("exam_sections").select("id, paper_id").in_("paper_id", paper_ids).execute()
        section_ids = []
        for s in (all_sections.data or []):
            sections_by_paper.setdefault(s["paper_id"], []).append({"id": s["id"]})
            section_ids.append(s["id"])
        if section_ids:
            all_questions = db.table("questions").select("id, section_id").in_("section_id", section_ids).execute()
            for q in (all_questions.data or []):
                question_count_by_section[q["section_id"]] = question_count_by_section.get(q["section_id"], 0) + 1

    formatted_sets = []
    for p in paper_rows:
        # We need to map the new schema to the old format expected by mcq/[seriesId]/page.tsx
        paper_sections = sections_by_paper.get(p["id"], [])
        question_count = sum(question_count_by_section.get(sec["id"], 0) for sec in paper_sections)

        formatted_sets.append({
            "id": p["id"],
            "title": p.get("title", "Test"),
            "description": p.get("test_type", "FULL_SUBJECT").replace("_", " "),
            "subject": p.get("level", ""),
            "is_locked": True if p.get("status") != "published" else False, # Keep locked if draft
            "price": p.get("price", 0),
            "sections": paper_sections,
            "questionCount": question_count,
        })

    # Sort so published ones show up unlocked at the top
    formatted_sets.sort(key=lambda x: x["is_locked"])
    
    return {**series_mock, "sets": formatted_sets}


# ─── Student MCQ Catalog ─────────────────────────────────────────────────────

@router.get("/api/mcq/catalog")
async def get_mcq_catalog(
    level: Optional[str] = None,
    group_name: Optional[str] = None,
    subject_code: Optional[str] = None,
    test_type: Optional[str] = None,
    db: Client = Depends(get_db),
):
    """Returns published MCQ sets structured for student browsing."""
    try:
        query = db.table("mcq_papers").select("*").eq("status", "published")
        if level:
            query = query.eq("level", level.upper())
        if group_name:
            query = query.eq("group_name", group_name)
        if subject_code:
            query = query.eq("subject_code", subject_code.upper())
        if test_type:
            query = query.eq("test_type", test_type)

        sets_res = query.order("created_at", desc=True).execute()
        sets_data = [p for p in (sets_res.data or []) if not scholarship.is_scholarship(p)]

        # Batched instead of 2 extra round trips (exam_sections + questions
        # count) per set — same fix as mcq/[seriesId]'s get_series.
        paper_ids = [s["id"] for s in sets_data]
        sections_by_paper: Dict[str, list] = {pid: [] for pid in paper_ids}
        q_count_by_paper: Dict[str, int] = {pid: 0 for pid in paper_ids}
        if paper_ids:
            all_sections = db.table("exam_sections").select("id, paper_id").in_("paper_id", paper_ids).execute()
            section_to_paper = {}
            for sec in (all_sections.data or []):
                sections_by_paper.setdefault(sec["paper_id"], []).append(sec)
                section_to_paper[sec["id"]] = sec["paper_id"]
            section_ids = list(section_to_paper.keys())
            if section_ids:
                all_questions = db.table("questions").select("id, section_id").in_("section_id", section_ids).execute()
                for q in (all_questions.data or []):
                    pid = section_to_paper.get(q["section_id"])
                    if pid:
                        q_count_by_paper[pid] = q_count_by_paper.get(pid, 0) + 1

        enriched = []
        for s in sets_data:
            sections = sections_by_paper.get(s["id"], [])
            q_count = q_count_by_paper.get(s["id"], 0)

            enriched.append({
                "id": s["id"],
                "seriesId": s.get("series_id"),
                "title": s.get("title", "Untitled Test"),
                "level": s.get("level", "FINAL"),
                "groupName": s.get("group_name", "GROUP_1"),
                "subjectCode": s.get("subject_code") or s.get("subject", ""),
                "testType": s.get("test_type", "FULL_SUBJECT"),
                "chapterName": s.get("chapter_name"),
                "durationMinutes": s.get("duration_minutes", 60),
                "passingMarks": float(s.get("passing_marks") or 40.0),
                "totalMarks": float(s.get("total_marks") or 30.0),
                "isLocked": s.get("is_locked", False),
                "price": float(s.get("price") or 0.0),
                "description": s.get("description", ""),
                "subject": s.get("subject", ""),
                "sectionCount": len(sections),
                "questionCount": q_count,
            })
        return enriched
    except Exception:
        return []


# ─── Quiz Sets / Attempts / Analytics ────────────────────────────────────────

# Roles that may open any paper regardless of purchase or publish status.
# mcq_editor is deliberately absent: editors author in the admin studio and
# are treated as students here.
_PREVIEW_ROLES = {"admin", "super_admin", "mentor"}


def _hide_unpublished(current_user: dict, paper: dict) -> None:
    """404 an unpublished (draft/archived) paper for anyone outside staff.

    The purchase check below only runs for papers flagged is_locked, so
    without this an unlocked draft was open to every logged-in user. 404
    rather than 403 so a draft's existence isn't confirmed. Submitting needs
    an attempt started on this same paper, so gating load and start covers
    submit too — while still letting an attempt begun on a published paper
    finish if that paper is archived mid-way."""
    if paper.get("status") != "published" and current_user.get("role") not in _PREVIEW_ROLES:
        raise HTTPException(status_code=404, detail="Quiz set not found")


async def _has_mcq_paper_access(current_user: dict, paper: dict, db: Client) -> bool:
    """Admins/mentors can always preview. Students need an active mcq_enrollments
    row for the paper's subject (matched via mcq_subjects.code + level -> its
    storefront id, which is what mcq_enrollments.subject_code stores)."""
    if current_user.get("role") in _PREVIEW_ROLES:
        return True
    if scholarship.is_scholarship(paper):
        # Bought per paper, not per subject.
        return scholarship.has_access(db, current_user["id"], paper["id"])

    subject_code = (paper.get("subject_code") or "").strip()
    level = (paper.get("level") or "").strip().upper()
    if not subject_code or not level:
        return False

    sub_res = (
        db.table("mcq_subjects")
        .select("id")
        .ilike("code", subject_code)
        .eq("level", level)
        .execute()
    )
    if not sub_res.data:
        return False
    storefront_id = sub_res.data[0]["id"]

    now = datetime.now(timezone.utc)
    enroll_res = (
        db.table("mcq_enrollments")
        .select("access_until")
        .eq("user_id", current_user["id"])
        .eq("subject_code", storefront_id)
        .execute()
    )
    for row in (enroll_res.data or []):
        expiry = row.get("access_until")
        if not expiry:
            return True  # lifetime access
        try:
            expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            if expiry_dt > now:
                return True
        except ValueError:
            continue
    return False


def _locked_message(paper: dict) -> str:
    if scholarship.is_scholarship(paper):
        return "Register for the Scholarship Test to take it."
    return "Purchase this subject to access this test"


def _sorted_by_order_index(rows: list) -> list:
    """Defense-in-depth: explicitly sort by order_index in Python even though
    the query already requests .order("order_index"), so ordering is never
    silently dependent on the DB/PostgREST's implicit row order."""
    return sorted(rows, key=lambda r: r.get("order_index") if r.get("order_index") is not None else 0)


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("/api/quizzes/{set_id}")
async def get_quiz(set_id: str, current_user: dict = Depends(get_current_user), db: Client = Depends(get_db)):
    """Returns quiz sections/questions for attempting. Never includes the answer
    key — correct_option/explanation are only returned by submit-v2, after the
    student has actually submitted an attempt."""
    mcq_set = db.table("mcq_papers").select("*").eq("id", set_id).single().execute()
    if not mcq_set.data:
        raise HTTPException(status_code=404, detail="Quiz set not found")
    _hide_unpublished(current_user, mcq_set.data)

    if mcq_set.data.get("is_locked") or scholarship.is_scholarship(mcq_set.data):
        if not await _has_mcq_paper_access(current_user, mcq_set.data, db):
            raise HTTPException(status_code=403, detail=_locked_message(mcq_set.data))

    # Fetch sections
    sections_res = db.table("exam_sections").select("*").eq("paper_id", set_id).order("order_index").execute()
    sections = _sorted_by_order_index(sections_res.data or [])

    enriched_sections = []
    for section in sections:
        questions_res = (
            db.table("questions")
            .select("*")
            .eq("section_id", section["id"])
            .order("order_index")
            .execute()
        )
        mapped_questions = []
        for q in _sorted_by_order_index(questions_res.data or []):
            mapped_questions.append({
                "id": q["id"],
                "type": q.get("type", "normal"),
                "case_narrative": q.get("case_narrative", ""),
                "case_group_id": q.get("case_group_id"),
                "chapterTag": q.get("chapter_tag"),
                "difficulty": q.get("difficulty", "medium"),
                "marks": float(q.get("marks") or 1.0),
                "negativeMarks": float(q.get("negative_marks") or 0.0),
                "text": q.get("content", ""),
                "options": q["options"],
                # NOTE: correct_option/explanation intentionally omitted — this
                # endpoint is used to render the quiz-taking UI, before grading.
                # The answer key is only ever returned by submit-v2's response.
            })
        enriched_sections.append({
            "id": section["id"],
            "title": section["title"],
            "questions": mapped_questions
        })

    data = mcq_set.data
    return {
        "id": data["id"],
        "seriesId": data.get("series_id"),
        "title": data["title"],
        "level": data.get("level", "FINAL"),
        "groupName": data.get("group_name", "GROUP_1"),
        "subjectCode": data.get("subject_code") or data.get("subject", ""),
        "testType": data.get("test_type", "FULL_SUBJECT"),
        "chapterName": data.get("chapter_name"),
        "durationMinutes": int(data.get("duration_minutes") or 60),
        "passingMarks": float(data.get("passing_marks") or 40.0),
        "totalMarks": float(data.get("total_marks") or 30.0),
        "shuffleQuestions": bool(data.get("shuffle_questions", False)),
        "shuffleOptions": bool(data.get("shuffle_options", False)),
        "allowRetake": bool(data.get("allow_retake", True)),
        "maxAttempts": data.get("max_attempts"),
        "isLocked": data.get("is_locked", False),
        "price": float(data.get("price") or 0.0),
        "description": data.get("description", ""),
        "subject": data.get("subject", ""),
        "topperStats": {
            "score": data.get("topper_score", 0),
            "totalTimeSeconds": data.get("topper_total_time_seconds", 0),
            "perQuestionTimes": data.get("topper_per_question_times", []),
        },
        "sections": enriched_sections,
    }


def _attempt_response(row: dict, resumed: bool) -> dict:
    started_at = _parse_dt(row["started_at"])
    duration_minutes = int(row["duration_minutes"])
    deadline = started_at + timedelta(minutes=duration_minutes)
    return {
        "attemptId": row["id"],
        "status": "resumed" if resumed else "started",
        "questionOrder": row.get("question_order") or [],
        "answers": row.get("answers") or {},
        "perQuestionTimes": row.get("per_question_times") or [],
        "currentIndex": row.get("current_index") or 0,
        "sectionElapsed": row.get("section_elapsed") or {},
        "startedAt": row["started_at"],
        "durationMinutes": duration_minutes,
        "deadlineAt": deadline.isoformat(),
    }


@router.post("/api/quizzes/{set_id}/attempt/start")
@limiter.limit("20/minute")
async def start_attempt(
    request: Request,
    set_id: str,
    body: AttemptStartRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Creates a new in-progress attempt, or resumes an existing one — at most
    one in-progress attempt per (user, paper) can exist (enforced by a unique
    partial index in the DB). Question order is computed client-side (the
    shuffle algorithm lives in quizLogic.ts and is intentionally not
    duplicated in Python) and persisted verbatim on first start; every
    subsequent resume replays that persisted order, ignoring whatever the
    client just recomputed, so a refreshed session never shows a different
    shuffle than the one the student started with."""
    user_id = current_user["id"]

    mcq_set = db.table("mcq_papers").select("*").eq("id", set_id).single().execute()
    if not mcq_set.data:
        raise HTTPException(status_code=404, detail="Quiz set not found")
    _hide_unpublished(current_user, mcq_set.data)
    if mcq_set.data.get("is_locked") or scholarship.is_scholarship(mcq_set.data):
        if not await _has_mcq_paper_access(current_user, mcq_set.data, db):
            raise HTTPException(status_code=403, detail=_locked_message(mcq_set.data))

    def _find_in_progress():
        return (
            db.table("mcq_attempt_sessions")
            .select("*")
            .eq("user_id", user_id)
            .eq("set_id", set_id)
            .eq("status", "in_progress")
            .execute()
        )

    existing = _find_in_progress()
    if existing.data:
        return _attempt_response(existing.data[0], resumed=True)

    # Enforce the paper's own retake policy — previously allowRetake/
    # maxAttempts were only ever surfaced to the frontend for display, never
    # actually checked server-side, so a direct call here could start
    # (and, via submit-v2, grade — see submit-v2's attemptId requirement)
    # unlimited attempts regardless of what the admin configured.
    allow_retake = bool(mcq_set.data.get("allow_retake", True))
    max_attempts = mcq_set.data.get("max_attempts")
    if scholarship.is_closed(mcq_set.data) and current_user.get("role") not in _PREVIEW_ROLES:
        raise HTTPException(status_code=403, detail="This Scholarship Test is closed — its results are out. If you took it, see your result in your dashboard.")
    if scholarship.is_scholarship(mcq_set.data) and current_user.get("role") not in _PREVIEW_ROLES:
        # One attempt, whatever the paper's retake settings say. Staff can
        # retake to try it out; their attempts aren't ranked.
        taken = (
            db.table("mcq_attempt_sessions").select("id")
            .eq("user_id", user_id).eq("set_id", set_id).eq("status", "submitted")
            .limit(1).execute().data
        )
        if taken:
            raise HTTPException(status_code=403, detail="You've already taken this test. Your result will appear in your dashboard once it's published.")
    elif not allow_retake or max_attempts:
        submitted_count_res = (
            db.table("mcq_attempt_sessions")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("set_id", set_id)
            .eq("status", "submitted")
            .execute()
        )
        submitted_count = submitted_count_res.count or 0
        limit = max_attempts if allow_retake else 1
        if limit is not None and submitted_count >= limit:
            raise HTTPException(status_code=403, detail="You've used all your attempts for this test.")

    if not body.questionOrder:
        raise HTTPException(status_code=400, detail="questionOrder is required to start an attempt")

    now_iso = datetime.now(timezone.utc).isoformat()
    new_row = {
        "id": f"att-{uuid.uuid4().hex[:16]}",
        "user_id": user_id,
        "set_id": set_id,
        "status": "in_progress",
        "question_order": body.questionOrder,
        "answers": {},
        "per_question_times": [0.0] * len(body.questionOrder),
        "current_index": 0,
        "section_elapsed": {},
        "started_at": now_iso,
        "duration_minutes": int(mcq_set.data.get("duration_minutes") or 60),
        "last_saved_at": now_iso,
    }
    try:
        db.table("mcq_attempt_sessions").insert(new_row).execute()
    except Exception:
        # Unique-index race: a concurrent request for this user+paper won
        # first. Return that one as a resume instead of erroring.
        existing = _find_in_progress()
        if existing.data:
            return _attempt_response(existing.data[0], resumed=True)
        raise HTTPException(status_code=500, detail="Could not start attempt")

    return _attempt_response(new_row, resumed=False)


@router.patch("/api/quizzes/{set_id}/attempt/{attempt_id}/progress")
@limiter.limit("60/minute")
async def save_attempt_progress(
    request: Request,
    set_id: str,
    attempt_id: str,
    body: AttemptProgressRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Autosave: persists in-progress answers/navigation state so a refresh or
    accidental navigation never loses a student's attempt. Rejects writes once
    the server-computed deadline has passed — the frontend auto-finalizes
    (calls submit-v2) when it sees status:"expired" back, so a client can't
    keep answering past the real deadline just by not calling this endpoint."""
    attempt = db.table("mcq_attempt_sessions").select("*").eq("id", attempt_id).execute()
    if not attempt.data:
        raise HTTPException(status_code=404, detail="Attempt not found")
    row = attempt.data[0]

    if row["user_id"] != current_user["id"] or row["set_id"] != set_id:
        raise HTTPException(status_code=403, detail="This attempt doesn't belong to you")

    if row["status"] != "in_progress":
        return {"success": False, "status": row["status"]}

    deadline = _parse_dt(row["started_at"]) + timedelta(minutes=int(row["duration_minutes"]))
    if datetime.now(timezone.utc) > deadline:
        return {"success": False, "status": "expired"}

    db.table("mcq_attempt_sessions").update({
        "answers": body.answers,
        "per_question_times": body.perQuestionTimes,
        "current_index": body.currentIndex,
        "section_elapsed": body.sectionElapsed,
        "last_saved_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", attempt_id).execute()

    return {"success": True}


@router.post("/api/quizzes/{set_id}/submit-v2")
@limiter.limit("20/minute")
async def submit_quiz_v2(
    request: Request,
    set_id: str,
    body: TestSubmissionV2Request,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Production ICAI scoring engine: computes marks with negative marking, accuracy, and topic analytics."""
    user_id = current_user["id"]

    # 1. Fetch full quiz set definition
    mcq_set = db.table("mcq_papers").select("*").eq("id", set_id).single().execute()
    if not mcq_set.data:
        raise HTTPException(status_code=404, detail="Quiz set not found")

    # Same entitlement check get_quiz already applies at retrieval time — a
    # student must not be able to call submit-v2 directly on a locked/
    # unpurchased paper and receive the full answer key in the response.
    if mcq_set.data.get("is_locked") or scholarship.is_scholarship(mcq_set.data):
        if not await _has_mcq_paper_access(current_user, mcq_set.data, db):
            raise HTTPException(status_code=403, detail=_locked_message(mcq_set.data))

    # attemptId is required (not just optional-and-trusted-if-present) —
    # without it this call used to skip all ownership/deadline checks and
    # just grade whatever "answers" were posted, returning the correct
    # option and explanation for every question. That let anyone harvest
    # the full answer key for any paper, unlimited times, without ever
    # calling attempt/start. The real frontend always sends attemptId
    # (quiz/[id]/page.tsx) — a direct call omitting it is exactly the oracle
    # this closes.
    if not body.attemptId:
        raise HTTPException(status_code=400, detail="No active attempt for this submission. Start the quiz again.")

    sections_res = db.table("exam_sections").select("*").eq("paper_id", set_id).order("order_index").execute()
    sections = _sorted_by_order_index(sections_res.data or [])

    # Flatten all questions across sections in canonical order_index order.
    # This order is authoritative for section/topic aggregation and for the
    # questionAnalysis array in the response — the client's own (possibly
    # shuffled) display order never affects grading, since answers are looked
    # up by question ID below, not by position.
    all_questions = []
    for sec in sections:
        q_res = (
            db.table("questions")
            .select("*")
            .eq("section_id", sec["id"])
            .order("order_index")
            .execute()
        )
        for q in _sorted_by_order_index(q_res.data or []):
            all_questions.append({
                "id": q["id"],
                "section_id": sec["id"],
                "section_title": sec["title"],
                "type": q.get("type", "normal"),
                "case_narrative": q.get("case_narrative", ""),
                "case_group_id": q.get("case_group_id"),
                "chapter_tag": q.get("chapter_tag") or mcq_set.data.get("chapter_name") or "General",
                "difficulty": q.get("difficulty", "medium"),
                "marks": float(q.get("marks") or 1.0),
                "negative_marks": float(q.get("negative_marks") or 0.0),
                "text": q.get("content", ""),
                "options": q["options"],
                "correct_option_index": int(q.get("correct_option", 0)),
                "explanation": q.get("explanation", "")
            })

    total_possible_marks = sum(q["marks"] for q in all_questions) if all_questions else float(mcq_set.data.get("total_marks") or 30.0)

    total_score = 0.0
    correct_count = 0
    incorrect_count = 0
    skipped_count = 0

    section_breakdown = {}
    topic_breakdown = {}
    question_analysis = []

    # Question-ID-keyed answers (question_id -> selected option index or null)
    # — the server-verifiable payload shape. Previously this was a positional
    # array graded against a separately-fetched, independently-ordered
    # question list, which silently mis-scored every answer whenever the
    # paper had shuffle enabled (the client's shuffled order never matched
    # this endpoint's own reconstruction).
    attempt = db.table("mcq_attempt_sessions").select("*").eq("id", body.attemptId).execute()
    if not attempt.data:
        raise HTTPException(status_code=404, detail="Attempt not found")
    attempt_row = attempt.data[0]
    if attempt_row["user_id"] != user_id or attempt_row["set_id"] != set_id:
        raise HTTPException(status_code=403, detail="This attempt doesn't belong to you")

    already_submitted = attempt_row["status"] == "submitted"
    deadline = _parse_dt(attempt_row["started_at"]) + timedelta(minutes=int(attempt_row["duration_minutes"]))
    is_late = datetime.now(timezone.utc) > deadline

    if not already_submitted:
        # Atomic claim (compare-and-swap): the WHERE ...eq("status","in_progress")
        # only matches — and only returns rows in `.data` — if this call is
        # the one that wins the race. On a winning, on-time claim, persist
        # the actually-submitted answers onto the attempt row itself (not
        # just used locally for grading) — otherwise a later replay of
        # this same attemptId would grade whatever the last autosave
        # happened to be, which can be stale/incomplete, instead of what
        # was really submitted here.
        claim_payload = {"status": "submitted", "submitted_at": datetime.now(timezone.utc).isoformat()}
        if not is_late:
            claim_payload["answers"] = body.answers
            claim_payload["per_question_times"] = body.perQuestionTimes
        claim = (
            db.table("mcq_attempt_sessions")
            .update(claim_payload)
            .eq("id", body.attemptId)
            .eq("status", "in_progress")
            .execute()
        )
        if not claim.data:
            # Lost the race — a concurrent call already claimed it a
            # moment ago. Fall through to the same handling as a genuine
            # resubmission below instead of erroring, so a real
            # double-click/retry still gets back a valid result.
            already_submitted = True
        else:
            attempt_row = claim.data[0]  # reflects what was just persisted

    # Once already submitted (a genuine resubmission, or a race we just
    # lost) or once past deadline, grade the persisted snapshot instead
    # of whatever the request body says. Scoring is a pure function of
    # (questions, answers), so replaying against the same stored answers
    # reproduces the exact same result deterministically — no need to
    # read back a separately stored row. This also closes the "keep
    # answering past the deadline" loophole for the late case.
    if already_submitted or is_late:
        user_answers = attempt_row["answers"]
        per_q_times = attempt_row["per_question_times"]
    else:
        user_answers = body.answers
        per_q_times = body.perQuestionTimes
    effective_elapsed_seconds = int(min(
        (datetime.now(timezone.utc) - _parse_dt(attempt_row["started_at"])).total_seconds(),
        int(attempt_row["duration_minutes"]) * 60,
    ))

    for idx, q in enumerate(all_questions):
        user_ans = user_answers.get(q["id"])
        time_spent = per_q_times[idx] if idx < len(per_q_times) else 0.0
        sec_title = q["section_title"]
        topic = q["chapter_tag"]

        # Initialize section aggregator
        if sec_title not in section_breakdown:
            section_breakdown[sec_title] = {"totalMarks": 0.0, "earnedMarks": 0.0, "correct": 0, "incorrect": 0, "skipped": 0}
        section_breakdown[sec_title]["totalMarks"] += q["marks"]

        # Initialize topic aggregator
        if topic not in topic_breakdown:
            topic_breakdown[topic] = {"totalMarks": 0.0, "earnedMarks": 0.0, "correct": 0, "incorrect": 0, "skipped": 0}
        topic_breakdown[topic]["totalMarks"] += q["marks"]

        # Scoring logic
        if user_ans is None:
            status = "skipped"
            earned = 0.0
            skipped_count += 1
            section_breakdown[sec_title]["skipped"] += 1
            topic_breakdown[topic]["skipped"] += 1
        elif user_ans == q["correct_option_index"]:
            status = "correct"
            earned = q["marks"]
            correct_count += 1
            section_breakdown[sec_title]["correct"] += 1
            topic_breakdown[topic]["correct"] += 1
        else:
            status = "incorrect"
            earned = -q["negative_marks"]
            incorrect_count += 1
            section_breakdown[sec_title]["incorrect"] += 1
            topic_breakdown[topic]["incorrect"] += 1

        total_score += earned
        section_breakdown[sec_title]["earnedMarks"] += earned
        topic_breakdown[topic]["earnedMarks"] += earned

        question_analysis.append({
            "questionIndex": idx,
            "questionId": q["id"],
            "sectionId": q["section_id"],
            "sectionTitle": sec_title,
            "chapterTag": topic,
            "type": q["type"],
            "caseNarrative": q["case_narrative"],
            "caseGroupId": q["case_group_id"],
            "status": status,
            "userSelected": user_ans,
            "correctOptionIndex": q["correct_option_index"],
            "marks": q["marks"],
            "negativeMarks": q["negative_marks"],
            "marksEarned": earned,
            "timeTakenSeconds": time_spent,
            "text": q.get("content", ""),
            "options": q["options"],
            "explanation": q["explanation"]
        })

    # Floor score at 0 if needed or keep raw
    final_score = max(0.0, round(total_score, 2))
    percentage = round((final_score / max(1.0, total_possible_marks)) * 100, 2)
    passing_cutoff = float(mcq_set.data.get("passing_marks") or 40.0)
    is_passed = percentage >= passing_cutoff
    attempted_count = correct_count + incorrect_count
    accuracy = round((correct_count / max(1, attempted_count)) * 100, 2) if attempted_count > 0 else 0.0
    avg_time = round(effective_elapsed_seconds / max(1, len(all_questions)), 1) if all_questions else 0.0

    submission_id = f"sub-{uuid.uuid4().hex[:12]}"

    # Persisted once per attempt only — a replayed/raced resubmission
    # (already_submitted) must not insert a second leaderboard row or
    # duplicate the result record. Note: this writes to quiz_attempts, not
    # test_submissions — that table belongs to the unrelated test-series
    # (PDF paper evaluation) feature and has a completely different schema;
    # an MCQ result written there would silently fail (wrong columns).
    if not already_submitted:
        try:
            db.table("quiz_attempts").insert({
                "user_id": user_id,
                "set_id": set_id,
                "score": int(final_score),
                "total": int(total_possible_marks),
                "elapsed_seconds": effective_elapsed_seconds,
                "per_question_times": per_q_times,
                "user_answers": user_answers,
                "section_scores": section_breakdown,
                "topic_scores": topic_breakdown,
                "full_question_analysis": question_analysis,
                "status": "evaluated",
            }).execute()
        except Exception:
            pass

    # Scholarship test: the attempt is stored above, but marks, answers and
    # rank stay hidden until an admin publishes the results.
    if scholarship.is_scholarship(mcq_set.data):
        return {"setId": set_id, "resultPending": True}

    # Calculate Rank & Percentile
    try:
        better = (
            db.table("quiz_attempts")
            .select("id")
            .eq("set_id", set_id)
            .or_(
                f"score.gt.{final_score},"
                f"and(score.eq.{final_score},elapsed_seconds.lt.{effective_elapsed_seconds})"
            )
            .execute()
        )
        rank = len(better.data or []) + 1
        total_res = db.table("quiz_attempts").select("id", count="exact").eq("set_id", set_id).execute()
        total_comp = max(1, total_res.count or 1)
        percentile = round(((total_comp - rank + 1) / total_comp) * 100, 1)
    except Exception:
        rank = 1
        total_comp = 1
        percentile = 100.0

    return {
        "submissionId": submission_id,
        "setId": set_id,
        "score": final_score,
        "totalMarks": total_possible_marks,
        "percentage": percentage,
        "isPassed": is_passed,
        "correctCount": correct_count,
        "incorrectCount": incorrect_count,
        "skippedCount": skipped_count,
        "accuracyPercentage": accuracy,
        "averageTimePerQuestion": avg_time,
        "totalTimeSeconds": effective_elapsed_seconds,
        "rank": rank,
        "totalCompetitors": total_comp,
        "percentile": percentile,
        "sectionBreakdown": section_breakdown,
        "topicBreakdown": topic_breakdown,
        "questionAnalysis": question_analysis
    }


# NOTE: the old POST /api/quizzes/{set_id}/attempts "legacy" route was
# removed here — it inserted a client-supplied score/total straight into
# quiz_attempts with no grading, no answer-key comparison, and no rate
# limit, which let anyone forge a leaderboard-topping score for any quiz.
# It was never called by the current frontend (submit-v2 above is the real,
# server-graded submission path); if a legacy client still depends on it,
# it must be rebuilt to recompute the score server-side the same way
# submit-v2 does, never trust a client-supplied score/total.


@router.get("/api/quizzes/{set_id}/leaderboard")
@limiter.limit("30/minute")
async def get_leaderboard(
    request: Request,
    set_id: str,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Returns top 20 attempts sorted by score desc, then time asc."""
    paper = db.table("mcq_papers").select("*").eq("id", set_id).execute().data or []
    if paper and scholarship.is_scholarship(paper[0]):
        return []  # ranks are only shown to admins (Admin → Leaderboard)
    attempts = (
        db.table("quiz_attempts")
        .select("user_id, score, elapsed_seconds")
        .eq("set_id", set_id)
        .order("score", desc=True)
        .order("elapsed_seconds", desc=False)
        .limit(20)
        .execute()
    )

    attempt_rows = attempts.data or []

    # Batched instead of one profiles lookup per attempt.
    user_ids = list({a["user_id"] for a in attempt_rows})
    names_by_user: Dict[str, str] = {}
    if user_ids:
        profiles = db.table("profiles").select("id, full_name").in_("id", user_ids).execute()
        for p in (profiles.data or []):
            names_by_user[p["id"]] = p.get("full_name") or "Student"

    board = []
    for a in attempt_rows:
        # Uses the student's own chosen display name, not their email —
        # deriving a "name" from the email's local-part (the old
        # behavior) leaked a real, private email address to every other
        # student attempting the same quiz.
        name = names_by_user.get(a["user_id"], "Student")

        board.append({
            "name": name,
            "score": a["score"],
            "time": a["elapsed_seconds"],
            "isUser": a["user_id"] == current_user["id"],
        })
    return board

@router.get("/api/mcq/my-subjects")
@limiter.limit("40/minute")
async def get_my_subjects(request: Request, current_user: dict = Depends(get_current_user), db: Client = Depends(get_db)):
    from datetime import datetime, timezone
    
    # Fetch all enrollments for this user, ordered by access_until descending
    # Use created_at as tiebreaker — NULLs in access_until handled manually
    enrollments = db.table("mcq_enrollments")\
        .select("subject_code, access_until, level, created_at")\
        .eq("user_id", current_user["id"])\
        .execute()
    
    now = datetime.now(timezone.utc)
    valid_map = {}   # subject_code -> access_until string (ISO) or None
    level_map = {}
    
    for e in (enrollments.data or []):
        code = e["subject_code"]
        expiry_str = e.get("access_until")
        
        if expiry_str:
            try:
                expiry_date = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
                if expiry_date.tzinfo is None:
                    expiry_date = expiry_date.replace(tzinfo=timezone.utc)
                if now > expiry_date:
                    continue  # expired — skip
            except ValueError:
                pass
        
        # Keep the entry with the latest (furthest future) access_until per subject
        if code not in valid_map:
            valid_map[code] = expiry_str
            level_map[code] = e.get("level", "FINAL")
        else:
            # Replace if this entry has a later expiry
            existing = valid_map[code]
            if expiry_str and existing:
                try:
                    dt_new = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
                    if dt_new.tzinfo is None: dt_new = dt_new.replace(tzinfo=timezone.utc)
                    dt_old = datetime.fromisoformat(existing.replace("Z", "+00:00"))
                    if dt_old.tzinfo is None: dt_old = dt_old.replace(tzinfo=timezone.utc)
                    if dt_new > dt_old:
                        valid_map[code] = expiry_str
                        level_map[code] = e.get("level", "FINAL")
                except ValueError:
                    pass
            elif expiry_str and not existing:
                # Replace NULL with a real date
                valid_map[code] = expiry_str
                level_map[code] = e.get("level", "FINAL")
        
    enrolled_codes = list(valid_map.keys())
    if not enrolled_codes:
        return []
    
    # enrolled_codes are subject IDs like "final-afm" — match against mcq_subjects.id
    sub_res = db.table("mcq_subjects").select("*").in_("id", enrolled_codes).execute()
    subjects = sub_res.data or []
    
    series_list = []
    for s in subjects:
        sub_id = s["id"]  # "final-afm" — mcq_subjects PK, only used to look up access_until
        access_until = valid_map.get(sub_id)
        series_list.append({
            # /api/mcq-series/{id} (the route this "id" feeds) matches on
            # mcq_subjects.code / mcq_papers.subject_code, e.g. "AFM" — not
            # the long mcq_subjects.id. Routing with sub_id here silently
            # fell back to an empty placeholder every time.
            "id": s["code"],        # used for routing /mcq/AFM
            "code": s["code"],      # "AFM" — short display code
            "title": s["name"],
            "subject": f"{s['level']} \u2022 {s.get('group_name', '')}",
            "description": s.get("description", ""),
            "isLocked": False,
            "is_locked": False,
            "access_until": access_until,
        })
    return series_list
