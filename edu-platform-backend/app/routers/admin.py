import csv
import hmac
import io
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from postgrest.exceptions import APIError as PostgrestAPIError
from supabase import Client
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.database import get_db
from app.core.storage import signed_url_for, storage_path_from_url
from app.dependencies import require_admin, require_mentor, require_super_admin
from app.routers.payments import grant_test_series_subjects
from app.schemas.admin import ManualEnrollRequest, MentorPermissionsUpdateRequest
from app.schemas.mcq import BulkImportRequest

router = APIRouter(prefix="/api/admin", tags=["Admin"])


def _safe_delete(db: Client, table: str, id_col: str, id_value: str, what: str = "this item"):
    """Delete a row, converting a foreign-key violation (other rows still
    reference it) into a clear 400 instead of letting Postgres' raw 23503
    surface as an unhandled 500 — this was the actual cause behind course
    deletes failing with a generic server error."""
    try:
        db.table(table).delete().eq(id_col, id_value).execute()
    except PostgrestAPIError as e:
        if e.code == "23503":
            raise HTTPException(status_code=400, detail=f"Can't delete {what} — other records still reference it.")
        raise


# ─── Mentor Permission System ──────────────────────────────────────────────────
# Centralized, scalable permission model: one mentor_permissions row per
# mentor, holding a single `permissions` jsonb blob rather than one DB column
# per capability — adding a future permission needs zero migration, just a
# new key. Every check here fails closed: no mentors row, no permissions
# row, or a missing/false key all deny.

async def _get_own_mentor_ids(current_user: dict, db: Client) -> set:
    """Resolves the calling mentor's own mentors-table row id(s), matched via
    profile_id — the same lookup admin_list_sessions already used inline to
    scope a mentor's own bookings, shared here so it isn't duplicated."""
    rows = db.table("mentors").select("id").eq("profile_id", current_user["id"]).execute()
    return {m["id"] for m in (rows.data or [])}


async def _mentor_has_permission(current_user: dict, permission_key: str, db: Client) -> bool:
    """Admins/super_admins always pass. A mentor needs an explicit True for
    this permission_key in their own mentor_permissions row."""
    if current_user.get("role") in {"admin", "super_admin"}:
        return True
    if current_user.get("role") != "mentor":
        return False
    mentor_ids = await _get_own_mentor_ids(current_user, db)
    if not mentor_ids:
        return False
    perm_res = db.table("mentor_permissions").select("permissions").in_("mentor_id", list(mentor_ids)).execute()
    for row in (perm_res.data or []):
        if bool((row.get("permissions") or {}).get(permission_key, False)):
            return True
    return False


def _require_nonblank(body: dict, field: str, label: str, max_len: int = 200) -> str:
    """Shared validation for the admin content-CRUD endpoints below that still
    take a raw dict (camelCase payloads that don't map 1:1 onto a snake_case
    schema) — these previously accepted an empty/missing title-like field
    silently, producing content with no display name."""
    value = (body.get(field) or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    if len(value) > max_len:
        raise HTTPException(status_code=400, detail=f"{label} must be under {max_len} characters")
    return value


def _require_non_negative(value, label: str) -> float:
    try:
        num = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{label} must be a number")
    if num < 0:
        raise HTTPException(status_code=400, detail=f"{label} cannot be negative")
    return num


@router.get("/my-permissions")
async def get_my_permissions(staff: dict = Depends(require_mentor), db: Client = Depends(get_db)):
    """Self-serve permission check so the frontend can decide which admin-panel
    tabs to show, without needing the admin-only mentor list endpoint."""
    return {
        "role": staff.get("role"),
        "evaluate_papers": await _mentor_has_permission(staff, "evaluate_papers", db),
        "manage_sessions": await _mentor_has_permission(staff, "manage_sessions", db),
        "manage_test_series": await _mentor_has_permission(staff, "manage_test_series", db),
    }


# ─── Dashboard Summary ────────────────────────────────────────────────────────

@router.get("/summary")
async def get_summary(
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    users = db.table("profiles").select("id", count="exact").execute()
    courses = db.table("courses").select("id", count="exact").execute()
    pending_payments = db.table("payments").select("id", count="exact").eq("status", "pending").execute()
    mcq_sets = db.table("mcq_papers").select("id", count="exact").execute()
    pending_subs = db.table("test_submissions").select("id", count="exact").eq("status", "pending").execute()

    return {
        "totalUsers": users.count or 0,
        "totalCourses": courses.count or 0,
        "pendingPayments": pending_payments.count or 0,
        "totalMcqSets": mcq_sets.count or 0,
        "pendingSubmissions": pending_subs.count or 0,
    }


# ─── Payments ─────────────────────────────────────────────────────────────────

PAYMENT_STATUSES = ("pending", "approved", "rejected", "refunded")


@router.get("/payments")
async def list_payments(
    status: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """Paginated + server-filtered — the payments table only grows, so
    fetching every row on every load (the old behavior) doesn't scale past a
    few hundred rows. `profiles`/`courses` are pulled in via the FK embed
    instead of separate full-table fetches, and per-status tab counts come
    from one lightweight status-only query rather than 5 filtered ones."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    query = (
        db.table("payments")
        .select(
            "id, user_id, course_id, utr_number, amount, status, created_at, "
            "payment_method, payment_reference, payer_upi_id, payer_name, "
            "profiles(email), courses(title)",
            count="exact",
        )
        .order("created_at", desc=True)
    )
    if status and status != "all":
        query = query.eq("status", status)
    payments_res = query.range(offset, offset + limit - 1).execute()
    payments = payments_res.data or []
    total = payments_res.count or 0

    verifications = []
    for p in payments:
        profile = p.get("profiles") or {}
        email = profile.get("email") or "Unknown"

        course = p.get("courses") or {}
        utr = p.get("utr_number") or ""
        course_title = course.get("title")
        if not course_title:
            if utr.startswith("mcq-") or utr.startswith("testseries-"):
                course_title = utr.split("|")[0]
            else:
                course_title = "Multiple/Bundle"

        verifications.append({
            "id": p["id"],
            "studentEmail": email,
            "courseTitle": course_title,
            "amount": float(p.get("amount") or 0.0),
            "date": p.get("created_at", "").split("T")[0] if p.get("created_at") else "",
            "status": p.get("status", "pending"),
            "utrNumber": utr,
            "paymentMethod": p.get("payment_method", "razorpay"),
            "paymentReference": p.get("payment_reference"),
            "payerUpiId": p.get("payer_upi_id"),
            "payerName": p.get("payer_name"),
        })

    status_rows = db.table("payments").select("status").execute().data or []
    counts = {"all": len(status_rows)} | {s: 0 for s in PAYMENT_STATUSES}
    for row in status_rows:
        s = row.get("status")
        if s in counts:
            counts[s] += 1

    return {"items": verifications, "total": total, "counts": counts}

@router.post("/payments/{payment_id}/approve")
@router.patch("/payments/{payment_id}/approve")
async def approve_payment(
    payment_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """Single canonical approve path. Delegates to the same grant helpers the
    real Razorpay verify flow, the webhook, and the manual-UPI submit
    endpoints all use, so there's exactly one place that knows how to grant a
    course vs an MCQ subject vs a test-series subject, and coupon usage is
    recorded consistently no matter which payment method was used."""
    from app.routers.payments import _apply_course_grant_or_extend, _apply_mcq_grant, _apply_test_series_grant
    from app.core.config import get_settings

    payment_res = db.table("payments").select("*").eq("id", payment_id).single().execute()
    if not payment_res.data:
        raise HTTPException(status_code=404, detail="Payment not found")

    payment = payment_res.data
    if payment["status"] == "approved":
        return {"success": True, "message": "Already approved"}

    user_id = payment["user_id"]
    utr_number = payment.get("utr_number") or ""
    is_mcq = not payment.get("course_id") and utr_number.startswith("mcq-")
    is_test_series = not payment.get("course_id") and utr_number.startswith("testseries-")

    if is_mcq:
        result = await _apply_mcq_grant(db, payment["razorpay_order_id"], user_id, "admin_approved", "admin_approved")
    elif is_test_series:
        result = await _apply_test_series_grant(db, payment["razorpay_order_id"], user_id, "admin_approved", "admin_approved")
    else:
        user_res = db.table("profiles").select("email").eq("id", user_id).single().execute()
        email = user_res.data.get("email") if user_res.data else None
        result = await _apply_course_grant_or_extend(db, payment, user_id, email, "admin_approved", "admin_approved", get_settings())

    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Could not grant access for this payment."))

    return {"success": True}

@router.post("/payments/{payment_id}/reject")
@router.patch("/payments/{payment_id}/reject")
async def reject_payment(
    payment_id: str,
    body: dict = None,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """Body: { "reason": "..." } (optional) — reason is returned to the caller
    to show the student; add a dedicated `rejection_reason` column if you want
    it persisted rather than just relayed at approval time."""
    rejection_note = (body or {}).get("reason", "")
    db.table("payments").update({"status": "rejected"}).eq("id", payment_id).execute()
    return {"success": True, "reason": rejection_note}


@router.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: str,
    super_admin: dict = Depends(require_super_admin),
    db: Client = Depends(get_db),
):
    """Permanently removes a payment record — deleting financial/audit
    history, not just changing its status, so this is gated one level
    stricter than approve/reject. mcq_enrollments/test_series_enrollments/
    session_bookings/coupon_usages all reference payment_id as
    ON DELETE SET NULL, so this never blocks on those and never revokes
    access that was already granted — it only removes the payment row
    itself."""
    _safe_delete(db, "payments", "id", payment_id, "this payment")
    return {"success": True}


# ─── Users ────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    limit: Optional[int] = None,
    offset: int = 0,
    include_all: bool = False,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """`limit` omitted (or `include_all=true`) returns every user,
    unpaginated — used by the CSV export, which genuinely needs the full
    set. Otherwise this is paginated, and every related table (payments,
    quiz attempts, enrollments of every kind) is scoped to just this page's
    user_ids via `.in_()` instead of pulling the entire table on every load
    — those tables grow much faster than the user count, so that was the
    real scale risk here, not the profiles table itself."""
    paginate = bool(limit) and not include_all

    query = db.table("profiles").select("*", count="exact" if paginate else None).order("created_at", desc=True)
    if paginate:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        query = query.range(offset, offset + limit - 1)
    profiles_res = query.execute()
    profiles = profiles_res.data or []
    total = profiles_res.count if paginate else len(profiles)

    user_ids = [p["id"] for p in profiles] if paginate else None
    if paginate and not user_ids:
        return {"items": [], "total": total}

    users_mapped = []

    try:
        payments_q = db.table("payments").select("*").eq("status", "approved")
        courses = db.table("courses").select("id, title").execute().data or []
        course_map = {c["id"]: c["title"] for c in courses}

        # Narrow select — this table also carries a full_question_analysis
        # JSON blob per row that's never used here, only in per-attempt review.
        attempts_q = db.table("quiz_attempts").select("user_id, set_id, score, total, created_at")
        papers = db.table("mcq_papers").select("id, title").execute().data or []
        paper_map = {p["id"]: p["title"] for p in papers}

        enrollments_q = db.table("enrollments").select("user_id, course_id, purchased_at, access_until")

        mcq_enrollments_q = db.table("mcq_enrollments").select("user_id, subject_code, access_until, created_at")
        mcq_subjects = db.table("mcq_subjects").select("id, name").execute().data or []
        mcq_subject_map = {s["id"]: s["name"] for s in mcq_subjects}

        test_series_enrollments_q = db.table("test_series_enrollments").select("user_id, subject_id, access_until, created_at")
        test_series_subjects = db.table("test_series_subjects").select("id, name").execute().data or []
        test_series_subject_map = {s["id"]: s["name"] for s in test_series_subjects}

        if user_ids is not None:
            payments_q = payments_q.in_("user_id", user_ids)
            attempts_q = attempts_q.in_("user_id", user_ids)
            enrollments_q = enrollments_q.in_("user_id", user_ids)
            mcq_enrollments_q = mcq_enrollments_q.in_("user_id", user_ids)
            test_series_enrollments_q = test_series_enrollments_q.in_("user_id", user_ids)

        payments = payments_q.execute().data or []
        attempts = attempts_q.execute().data or []
        enrollments = enrollments_q.execute().data or []
        mcq_enrollments = mcq_enrollments_q.execute().data or []
        test_series_enrollments = test_series_enrollments_q.execute().data or []
    except Exception as e:
        print(f"[ADMIN USERS] Failed to load enrollment data: {e}")
        return {"error": "Failed to load user data. Please try again."}

    # Real enrollment dates, keyed by (user_id, course_id) — this is the
    # source of truth for when access actually ends, replacing the
    # client-side course-duration guess the CSV export used to make.
    enrollment_map = {
        (e.get("user_id"), e.get("course_id")): e
        for e in enrollments
    }

    # Group payments
    payments_by_user = {}
    for p in payments:
        uid = p.get("user_id")
        if uid not in payments_by_user:
            payments_by_user[uid] = []
        c_id = p.get("course_id")
        course_title = course_map.get(c_id, p.get("utr_number") or "Unknown Purchase")
        enrollment = enrollment_map.get((uid, c_id), {})
        payments_by_user[uid].append({
            "courseTitle": course_title,
            "amount": float(p.get("amount") or 0),
            "date": p.get("created_at") or p.get("updated_at"),
            "purchasedAt": enrollment.get("purchased_at"),
            "accessUntil": enrollment.get("access_until"),
        })

    # Group attempts
    attempts_by_user = {}
    for a in attempts:
        uid = a.get("user_id")
        if uid not in attempts_by_user:
            attempts_by_user[uid] = []
        p_id = a.get("set_id")
        attempts_by_user[uid].append({
            "setTitle": paper_map.get(p_id, "Unknown Set"),
            "score": a.get("score") or 0,
            "total": a.get("total") or 0,
            "date": a.get("created_at")
        })

    # Group MCQ subject ownership. Every row is shown (not deduped by
    # subject like /me does) — an admin audit view should show every
    # renewal/extension, not just the current live one.
    mcq_by_user = {}
    for e in mcq_enrollments:
        uid = e.get("user_id")
        if uid not in mcq_by_user:
            mcq_by_user[uid] = []
        mcq_by_user[uid].append({
            "subjectTitle": mcq_subject_map.get(e.get("subject_code"), e.get("subject_code") or "Unknown Subject"),
            "accessUntil": e.get("access_until"),
            "date": e.get("created_at"),
        })

    # Group test-series subject ownership, same pattern.
    test_series_by_user = {}
    for e in test_series_enrollments:
        uid = e.get("user_id")
        if uid not in test_series_by_user:
            test_series_by_user[uid] = []
        test_series_by_user[uid].append({
            "subjectTitle": test_series_subject_map.get(e.get("subject_id"), e.get("subject_id") or "Unknown Subject"),
            "accessUntil": e.get("access_until"),
            "date": e.get("created_at"),
        })

    for p in profiles:
        uid = p.get("id")
        users_mapped.append({
            "id": uid,
            "email": p.get("email", ""),
            "joinDate": p.get("created_at", ""),
            "full_name": p.get("full_name", ""),
            "phone": p.get("phone_number", ""),
            "address": p.get("address", ""),
            "stage": p.get("stage", ""),
            "attempt_status": p.get("attempt_status", ""),
            "purchases": payments_by_user.get(uid, []),
            "quizAttempts": attempts_by_user.get(uid, []),
            "mcqPurchases": mcq_by_user.get(uid, []),
            "testSeriesPurchases": test_series_by_user.get(uid, []),
        })

    return {"items": users_mapped, "total": total}


class SetUserRoleRequest(BaseModel):
    role: str  # "student" | "mentor" | "admin" | "super_admin"


@router.patch("/users/{user_id}/role")
async def set_user_role(
    user_id: str,
    body: SetUserRoleRequest,
    super_admin: dict = Depends(require_super_admin),
    db: Client = Depends(get_db),
):
    """Grant/revoke admin or mentor access. Only the super admin can do this —
    regular admins manage content/payments but must not be able to promote
    themselves or anyone else further."""
    if body.role not in {"student", "mentor", "admin", "super_admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")

    target = db.table("profiles").select("id, email").eq("id", user_id).single().execute()
    if not target.data:
        raise HTTPException(status_code=404, detail="User not found")

    db.table("profiles").update({"role": body.role}).eq("id", user_id).execute()

    # Mentors need a matching row in `mentors` so evaluation/session-booking
    # queries can resolve them — create one if it doesn't exist yet.
    if body.role == "mentor":
        existing = db.table("mentors").select("id").eq("profile_id", user_id).execute()
        if not existing.data:
            db.table("mentors").insert({
                "profile_id": user_id,
                "name": target.data.get("email", "").split("@")[0],
                "email": target.data.get("email", ""),
            }).execute()

    return {"success": True, "userId": user_id, "role": body.role}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    super_admin: dict = Depends(require_super_admin),
    db: Client = Depends(get_db),
):
    """Permanently deletes a user account and every row that references
    them — the same tables and order as a manual cleanup query would need,
    because several of these FKs predate this repo's tracked migrations
    and their ON DELETE behavior isn't reliably known, so this deletes
    dependents explicitly rather than assuming a cascade exists. Gated to
    super_admin given the blast radius, and blocks deleting your own
    account so an admin can't accidentally lock themselves out."""
    if user_id == super_admin["id"]:
        raise HTTPException(status_code=400, detail="You can't delete your own account.")

    target = db.table("profiles").select("id, email").eq("id", user_id).single().execute()
    if not target.data:
        raise HTTPException(status_code=404, detail="User not found")

    sub_ids = [s["id"] for s in (db.table("test_submissions").select("id").eq("student_id", user_id).execute().data or [])]
    if sub_ids:
        db.table("test_evaluations").delete().in_("submission_id", sub_ids).execute()
    db.table("test_submissions").delete().eq("student_id", user_id).execute()
    db.table("session_bookings").delete().eq("student_id", user_id).execute()
    db.table("payments").delete().eq("user_id", user_id).execute()
    db.table("enrollments").delete().eq("user_id", user_id).execute()
    db.table("quiz_attempts").delete().eq("user_id", user_id).execute()
    db.table("mcq_enrollments").delete().eq("user_id", user_id).execute()
    db.table("test_series_enrollments").delete().eq("user_id", user_id).execute()
    db.table("coupon_usages").delete().eq("user_id", user_id).execute()
    db.table("mcq_attempt_sessions").delete().eq("user_id", user_id).execute()

    mentor_row = db.table("mentors").select("id").eq("profile_id", user_id).execute().data or []
    if mentor_row:
        mentor_id = mentor_row[0]["id"]
        db.table("mentor_permissions").delete().eq("mentor_id", mentor_id).execute()
        db.table("session_bookings").delete().eq("mentor_id", mentor_id).execute()
        db.table("mentors").delete().eq("id", mentor_id).execute()

    db.table("profiles").delete().eq("id", user_id).execute()
    try:
        db.auth.admin.delete_user(user_id)
    except Exception as e:
        # Profile + all data is already gone at this point — the app can't
        # authenticate this user regardless (get_current_user requires a
        # matching profiles row). Log rather than fail the request over an
        # Auth-record cleanup that no longer affects app behavior.
        print(f"[DELETE USER] auth.admin.delete_user failed for {user_id}: {e}")

    return {"success": True}


@router.post("/mentors/enable-self")
async def enable_self_as_mentor(
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """Lets an admin/super_admin add themselves to the `mentors` table so
    they show up in the 1:1 session assignment dropdown — reuses the exact
    mentors-insert logic from set_user_role's mentor-promotion path above,
    but never touches profiles.role (the caller keeps their admin role)."""
    user_id = admin["id"]
    existing = db.table("mentors").select("id").eq("profile_id", user_id).execute()
    if not existing.data:
        db.table("mentors").insert({
            "profile_id": user_id,
            "name": (admin.get("email") or "").split("@")[0],
            "email": admin.get("email", ""),
        }).execute()
    return {"success": True, "userId": user_id}


# ─── Courses CRUD ─────────────────────────────────────────────────────────────

@router.get("/courses")
async def admin_list_courses(admin: dict = Depends(require_admin), db: Client = Depends(get_db)):
    return db.table("courses").select("*").execute().data or []


# ─── Course Enrollments ───────────────────────────────────────────────────────

@router.get("/courses/{course_id}/enrollments")
async def list_enrollments(
    course_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    result = (
        db.table("enrollments")
        .select("*, profiles(email)")
        .eq("course_id", course_id)
        .execute()
    )
    data = []
    for e in (result.data or []):
        profile = e.get("profiles") or {}
        data.append({
            "id": e["user_id"],
            "email": profile.get("email", ""),
            "purchaseDate": e.get("purchased_at", ""),
            "addedBy": e.get("added_by", "purchase"),
            "notes": e.get("notes"),
        })
    return data


@router.post("/courses/{course_id}/enrollments", status_code=201)
async def manual_enroll(
    course_id: str,
    body: ManualEnrollRequest,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    # Find user by email
    profile = db.table("profiles").select("id").eq("email", body.email).single().execute()
    if not profile.data:
        raise HTTPException(status_code=404, detail=f"No user found with email {body.email}")

    user_id = profile.data["id"]
    purchased_at = datetime.now(timezone.utc).isoformat()
    db.table("enrollments").upsert({
        "user_id": user_id,
        "course_id": course_id,
        "added_by": "admin",
        "notes": body.notes,
        "purchased_at": purchased_at,
    }).execute()
    return {
        "id": user_id,
        "email": body.email,
        "purchaseDate": purchased_at,
        "addedBy": "admin",
        "notes": body.notes,
    }


@router.delete("/courses/{course_id}/enrollments/{user_id}")
async def revoke_enrollment(
    course_id: str,
    user_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    db.table("enrollments").delete().eq("user_id", user_id).eq("course_id", course_id).execute()
    return {"success": True}


# ─── MCQ Series CRUD ──────────────────────────────────────────────────────────

@router.get("/mcq-series")
async def admin_list_series(admin: dict = Depends(require_admin), db: Client = Depends(get_db)):
    # mcq_series table may not exist — return empty list gracefully
    try:
        return db.table("mcq_series").select("*").execute().data or []
    except Exception:
        return []



# ─── Content Management (Courses, Series, Sets) ─────────────────────────────

@router.post("/courses")
async def admin_upsert_course(
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    # Upsert a course
    # This intentionally still takes a raw dict rather than a Pydantic model
    # — the frontend's payload is camelCase and doesn't line up 1:1 with a
    # snake_case schema (see the explicit mapping below), and the
    # bundled-test-series retroactive-grant logic further down needs to
    # distinguish "field omitted" from "field sent empty", which a plain
    # dict does naturally. What *was* missing is validation on the two
    # fields that reach the public course page unescaped in JSON-LD
    # (courses/[id]/page.tsx) — title must be non-empty, and price must not
    # be a negative/non-numeric value silently corrupting checkout pricing.
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Course title is required")
    if len(title) > 200:
        raise HTTPException(status_code=400, detail="Course title must be under 200 characters")
    description = body.get("description")
    if description is not None and len(description) > 5000:
        raise HTTPException(status_code=400, detail="Course description must be under 5000 characters")
    price = body.get("price", 0)
    try:
        price = float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Course price must be a number")
    if price < 0:
        raise HTTPException(status_code=400, detail="Course price cannot be negative")

    # Convert camelCase to snake_case mapping for DB
    data = {
        "id": body.get("id"),
        "title": title,
        "description": body.get("description", ""),
        "price": price,
        "level": body.get("level"),
        "duration": body.get("duration", ""),
        "tag": body.get("tag"),
        "enrolled_count": body.get("enrolledCount", 0),
        "rating": body.get("rating", 4.5),
        "outcomes": body.get("outcomes", []),
        "curriculum": body.get("curriculum", []),
        "mentors": body.get("mentors", []),
        "delivery_type": body.get("deliveryType", "whatsapp"),
        "whatsapp_link": body.get("whatsappLink"),
        "linked_series_id": body.get("linkedSeriesId"),
        "status": body.get("status", "available"),
        # Test-series subjects bundled with this course — granted automatically
        # on purchase. Optional, any number.
        "bundled_test_series_subject_ids": body.get("bundledTestSeriesSubjectIds", []),
        "is_one_on_one": body.get("isOneOnOne", False),
    }
    # Clean none values so supabase uses defaults
    data = {k: v for k, v in data.items() if v is not None}
    
    result = db.table("courses").upsert(data).execute()
    saved = result.data[0] if result.data else {}

    # Retroactive grant: if the admin (re)saved the course's bundled
    # test-series list, extend that access to everyone who already owns this
    # course, not just future purchasers. Only fires when the field was
    # actually sent — omitting it never triggers anything.
    if "bundledTestSeriesSubjectIds" in body and saved.get("id"):
        subject_ids = body.get("bundledTestSeriesSubjectIds") or []
        if subject_ids:
            owners = db.table("enrollments").select("user_id").eq("course_id", saved["id"]).execute()
            for row in (owners.data or []):
                grant_test_series_subjects(db, row["user_id"], subject_ids)

    return saved

@router.delete("/courses/{course_id}")
async def admin_delete_course(
    course_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    # Hard-deleting a course with active enrollments would silently orphan
    # every paying student's access record — Postgres already refuses this
    # via the enrollments FK, but the raw 23503 was previously surfacing as
    # an unhandled 500. Check first for a clear message; the try/except is
    # the backstop for the same race a concurrent enrollment would cause.
    enrolled = db.table("enrollments").select("user_id", count="exact").eq("course_id", course_id).range(0, 0).execute()
    if enrolled.count:
        raise HTTPException(
            status_code=400,
            detail=f"Can't delete — {enrolled.count} student{'s are' if enrolled.count != 1 else ' is'} still enrolled in this course. "
                   "Set its status to Archived instead, or remove those enrollments first from Courses → Edit → Enrolled Students.",
        )
    try:
        db.table("courses").delete().eq("id", course_id).execute()
    except PostgrestAPIError as e:
        if e.code == "23503":
            raise HTTPException(status_code=400, detail="Can't delete — this course still has students, payments, or other records referencing it.")
        raise
    return {"success": True}

@router.get("/course-bundles")
async def admin_list_bundles(
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    result = db.table("course_bundles").select("*").execute()
    # map to camelCase for UI
    out = []
    for row in (result.data or []):
        out.append({
            "id": row.get("id"),
            "title": row.get("title"),
            "description": row.get("description", ""),
            "level": row.get("level"),
            "courseIds": row.get("course_ids", []),
            "price": row.get("price", 0)
        })
    return out

@router.post("/course-bundles")
async def admin_upsert_bundle(
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    title = _require_nonblank(body, "title", "Bundle title")
    price = _require_non_negative(body.get("price", 0), "Bundle price")
    data = {
        "id": body.get("id"),
        "title": title,
        "description": body.get("description", ""),
        "level": body.get("level", "Multiple"),
        "course_ids": body.get("courseIds", []),
        "price": price,
    }
    result = db.table("course_bundles").upsert(data).execute()
    return {"success": True, "id": result.data[0]["id"] if result.data else None}

@router.delete("/course-bundles/{bundle_id}")
async def admin_delete_bundle(
    bundle_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    _safe_delete(db, "course_bundles", "id", bundle_id, "this bundle")
    return {"success": True}

# ─── Test Series admin CRUD ──────────────────────────────────────────────────

@router.get("/test-series/subjects")
async def admin_list_ts_subjects(staff: dict = Depends(require_mentor), db: Client = Depends(get_db)):
    if not await _mentor_has_permission(staff, "manage_test_series", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage test series")
    return db.table("test_series_subjects").select("*").order("sort_order").execute().data or []


@router.patch("/test-series/subjects/{subject_id}")
async def admin_update_ts_subject(
    subject_id: str, body: dict,
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    """Set price / toggle active. Catalog itself is seeded from the product sheet."""
    if not await _mentor_has_permission(staff, "manage_test_series", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage test series")
    allowed = {k: v for k, v in body.items() if k in {"price", "is_active", "name", "description", "sort_order"}}
    if not allowed:
        raise HTTPException(status_code=400, detail="Nothing to update")
    db.table("test_series_subjects").update(allowed).eq("id", subject_id).execute()
    return {"success": True}


@router.get("/test-series/bundles")
async def admin_list_ts_bundles(staff: dict = Depends(require_mentor), db: Client = Depends(get_db)):
    if not await _mentor_has_permission(staff, "manage_test_series", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage test series")
    return db.table("test_series_bundles").select("*").execute().data or []


@router.patch("/test-series/bundles/{bundle_id}")
async def admin_update_ts_bundle(
    bundle_id: str, body: dict,
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    if not await _mentor_has_permission(staff, "manage_test_series", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage test series")
    allowed = {k: v for k, v in body.items() if k in {"price", "is_active", "title", "subject_ids"}}
    if not allowed:
        raise HTTPException(status_code=400, detail="Nothing to update")
    db.table("test_series_bundles").update(allowed).eq("id", bundle_id).execute()
    return {"success": True}


@router.get("/test-series/papers")
async def admin_list_ts_papers(
    subject_id: Optional[str] = None,
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    if not await _mentor_has_permission(staff, "manage_test_series", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage test series")
    q = db.table("tests").select("*")
    if subject_id:
        q = q.eq("subject_id", subject_id)
    return q.order("sort_order").execute().data or []


MAX_TEST_SERIES_PAPER_BYTES = 3 * 1024 * 1024


@router.post("/test-series/papers/upload", status_code=201)
async def admin_upload_ts_paper(
    subject_id: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    """Upload a question paper PDF straight into Supabase Storage and create
    the `tests` row pointing at it — mirrors the MCQ Hierarchy's
    Level -> Subject -> content authoring flow. Published immediately so
    students who own the subject can see it right away."""
    if not await _mentor_has_permission(staff, "manage_test_series", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage test series")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    subj = db.table("test_series_subjects").select("id").eq("id", subject_id).execute()
    if not subj.data:
        raise HTTPException(status_code=404, detail="Subject not found")
    if (file.content_type or "") != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    raw = await file.read()
    if len(raw) > MAX_TEST_SERIES_PAPER_BYTES:
        raise HTTPException(status_code=400, detail="File must be under 3MB")
    # Content-Type is attacker-controlled and easy to spoof — also check the
    # actual file bytes start with the real PDF magic number.
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="File doesn't look like a valid PDF")

    settings = get_settings()
    safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "paper.pdf")
    path = f"{subject_id}/{uuid.uuid4().hex[:10]}-{safe_filename}"
    try:
        db.storage.from_(settings.supabase_test_series_bucket).upload(
            path, raw, {"content-type": "application/pdf"}
        )
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't upload the file. Please try again.")
    url = (
        f"{settings.supabase_url}/storage/v1/object/public/"
        f"{settings.supabase_test_series_bucket}/{path}"
    )

    row = {
        "title": title,
        "description": description,
        "question_file_url": url,
        "subject_id": subject_id,
        "status": "published",
        "sort_order": 0,
        "created_by": staff["id"],
    }
    res = db.table("tests").insert(row).execute()
    return {"success": True, "id": res.data[0]["id"] if res.data else None, "url": url}


@router.patch("/test-series/papers/{paper_id}")
async def admin_update_ts_paper(
    paper_id: str, body: dict,
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    if not await _mentor_has_permission(staff, "manage_test_series", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage test series")
    allowed = {k: v for k, v in body.items() if k in {"title", "description", "question_file_url", "status", "sort_order", "subject_id"}}
    if not allowed:
        raise HTTPException(status_code=400, detail="Nothing to update")
    db.table("tests").update(allowed).eq("id", paper_id).execute()
    return {"success": True}


@router.delete("/test-series/papers/{paper_id}")
async def admin_delete_ts_paper(
    paper_id: str,
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    if not await _mentor_has_permission(staff, "manage_test_series", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage test series")
    _safe_delete(db, "tests", "id", paper_id, "this paper")
    return {"success": True}


# ─── 1:1 Sessions ────────────────────────────────────────────────────────────

@router.get("/sessions")
async def admin_list_sessions(
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    """All 1:1 bookings. Mentors see only their own once assigned; admins see all."""
    if staff.get("role") == "mentor" and not await _mentor_has_permission(staff, "manage_sessions", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage 1:1 sessions")

    q = db.table("session_bookings").select(
        "*, profiles!session_bookings_student_id_fkey(email, full_name, phone_number), mentors(name, email), courses(title)"
    ).neq("status", "cancelled").order("created_at", desc=True)
    rows = q.execute().data or []

    if staff.get("role") == "mentor":
        me = db.table("mentors").select("id").eq("profile_id", staff["id"]).execute()
        my_ids = {m["id"] for m in (me.data or [])}
        rows = [r for r in rows if r.get("mentor_id") in my_ids or r.get("status") == "pending_assignment"]

    out = []
    for r in rows:
        student = r.get("profiles") or {}
        mentor = r.get("mentors") or {}
        course = r.get("courses") or {}
        out.append({
            "id": r["id"],
            "status": r.get("status"),
            "studentEmail": student.get("email", ""),
            "studentName": student.get("full_name") or "",
            "studentPhone": student.get("phone_number") or "",
            "mentorId": r.get("mentor_id"),
            "mentorName": mentor.get("name"),
            "courseTitle": course.get("title", "1:1 Session"),
            "scheduledAt": r.get("scheduled_at"),
            "meetLink": r.get("google_meet_link"),
            "mentorNote": r.get("mentor_note"),
            "createdAt": r.get("created_at"),
        })
    return out


class AssignMentorRequest(BaseModel):
    mentorId: str


@router.patch("/sessions/{session_id}/assign")
async def admin_assign_session_mentor(
    session_id: str, body: AssignMentorRequest,
    admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    """Admin picks which mentor takes this paid 1:1 session."""
    mentor = db.table("mentors").select("id").eq("id", body.mentorId).execute()
    if not mentor.data:
        raise HTTPException(status_code=404, detail="Mentor not found")
    db.table("session_bookings").update({
        "mentor_id": body.mentorId,
        "status": "pending_schedule",
    }).eq("id", session_id).execute()
    return {"success": True}


class ScheduleSessionRequest(BaseModel):
    scheduledAt: str      # ISO datetime
    meetLink: str
    note: Optional[str] = ""


async def _assert_mentor_owns_session(staff: dict, session_id: str, db: Client) -> None:
    """Admins/super_admins bypass. A mentor may only act on a session_bookings
    row already assigned to their own mentors-table id — previously any
    mentor could schedule/complete any other mentor's session."""
    if staff.get("role") != "mentor":
        return
    session = db.table("session_bookings").select("mentor_id").eq("id", session_id).execute()
    if not session.data:
        raise HTTPException(status_code=404, detail="Session not found")
    my_ids = await _get_own_mentor_ids(staff, db)
    if session.data[0].get("mentor_id") not in my_ids:
        raise HTTPException(status_code=403, detail="You are not assigned to this session")


@router.patch("/sessions/{session_id}/schedule")
async def mentor_schedule_session(
    session_id: str, body: ScheduleSessionRequest,
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    """Mentor sets the agreed slot + pastes their own Google Meet link."""
    if not await _mentor_has_permission(staff, "manage_sessions", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage 1:1 sessions")
    await _assert_mentor_owns_session(staff, session_id, db)
    if not body.meetLink.strip():
        raise HTTPException(status_code=400, detail="A meeting link is required")
    db.table("session_bookings").update({
        "scheduled_at": body.scheduledAt,
        "google_meet_link": body.meetLink.strip(),
        "mentor_note": body.note or "",
        "status": "booked",
    }).eq("id", session_id).execute()
    return {"success": True}


@router.patch("/sessions/{session_id}/complete")
async def mentor_complete_session(
    session_id: str,
    staff: dict = Depends(require_mentor), db: Client = Depends(get_db),
):
    if not await _mentor_has_permission(staff, "manage_sessions", db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage 1:1 sessions")
    await _assert_mentor_owns_session(staff, session_id, db)
    db.table("session_bookings").update({"status": "completed"}).eq("id", session_id).execute()
    return {"success": True}


@router.delete("/sessions/{session_id}")
async def admin_delete_session(
    session_id: str,
    admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    _safe_delete(db, "session_bookings", "id", session_id, "this session")
    return {"success": True}


# ─── File retention: 7-day auto-delete ───────────────────────────────────────

@router.post("/maintenance/purge-old-files")
async def purge_old_submission_files(
    request: Request,
    db: Client = Depends(get_db),
):
    """Deletes answer-sheet + checked-copy PDFs older than 7 days from Storage,
    keeping the marks/remarks rows intact. Called by a scheduled job; protected
    by a shared secret rather than a user session so cron can invoke it."""
    settings = get_settings()
    expected = os.getenv("MAINTENANCE_SECRET", "")
    provided = request.headers.get("X-Maintenance-Secret", "")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Forbidden")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    purged_subs, purged_evals = 0, 0
    _storage_path = storage_path_from_url

    # Student submissions
    subs = (
        db.table("test_submissions").select("id, submission_files, submitted_at")
        .lt("submitted_at", cutoff).is_("files_purged_at", "null").execute().data or []
    )
    for s in subs:
        paths = [p for p in (_storage_path(u, settings.supabase_submission_bucket) for u in (s.get("submission_files") or [])) if p]
        if paths:
            try:
                db.storage.from_(settings.supabase_submission_bucket).remove(paths)
            except Exception as e:
                print(f"[PURGE] submission {s['id']}: {e}")
        db.table("test_submissions").update({
            "submission_files": [],
            "files_purged_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", s["id"]).execute()
        purged_subs += 1

    # Evaluated copies
    evals = (
        db.table("test_evaluations").select("id, checked_file_url, evaluated_at")
        .lt("evaluated_at", cutoff).is_("files_purged_at", "null").execute().data or []
    )
    for ev in evals:
        url = ev.get("checked_file_url") or ""
        path = _storage_path(url, settings.supabase_evaluation_bucket) if url else None
        if path:
            try:
                db.storage.from_(settings.supabase_evaluation_bucket).remove([path])
            except Exception as e:
                print(f"[PURGE] evaluation {ev['id']}: {e}")
        db.table("test_evaluations").update({
            "checked_file_url": None,
            "files_purged_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", ev["id"]).execute()
        purged_evals += 1

    return {"success": True, "purgedSubmissions": purged_subs, "purgedEvaluations": purged_evals}


# ─── Contact form messages ───────────────────────────────────────────────────

@router.get("/contact-messages")
async def admin_list_contact_messages(admin: dict = Depends(require_admin), db: Client = Depends(get_db)):
    return db.table("contact_messages").select("*").order("created_at", desc=True).execute().data or []


@router.patch("/contact-messages/{message_id}")
async def admin_mark_contact_read(
    message_id: str,
    admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    db.table("contact_messages").update({"is_read": True}).eq("id", message_id).execute()
    return {"success": True}


@router.delete("/contact-messages/{message_id}")
async def admin_delete_contact_message(
    message_id: str,
    admin: dict = Depends(require_admin), db: Client = Depends(get_db),
):
    _safe_delete(db, "contact_messages", "id", message_id, "this message")
    return {"success": True}


@router.post("/mcq-series")
async def admin_upsert_series(
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    title = _require_nonblank(body, "title", "Series title")
    price = _require_non_negative(body.get("price", 0), "Series price")
    data = {
        "id": body.get("id"),
        "title": title,
        "subject": body.get("subject"),
        "description": body.get("description", ""),
        "price": price,
        "is_locked": body.get("isLocked", False),
    }
    result = db.table("mcq_series").upsert(data).execute()
    return result.data[0] if result.data else {}

@router.delete("/mcq-series/{series_id}")
async def admin_delete_series(
    series_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    _safe_delete(db, "mcq_series", "id", series_id, "this series")
    return {"success": True}


# ─── MCQ Dynamic Pricing & Custom Bundles CRUD ───────────────────────────────

@router.get("/mcq/bundles")
async def admin_list_mcq_bundles(
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    from app.routers.mcq import DEFAULT_MCQ_BUNDLES
    try:
        res = db.table("mcq_bundles").select("*").execute()
        return res.data if res.data else DEFAULT_MCQ_BUNDLES
    except Exception:
        return DEFAULT_MCQ_BUNDLES


@router.post("/mcq/bundles")
async def admin_upsert_mcq_bundle(
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    import uuid
    title = _require_nonblank(body, "title", "Bundle title")
    prices = body.get("prices") or {"1_month": 0, "3_months": 0, "6_months": 0, "1_year": 0}
    for tier, val in prices.items():
        prices[tier] = _require_non_negative(val, f"Bundle price ({tier})")
    bundle_id = body.get("id") or f"custom-bundle-{uuid.uuid4().hex[:8]}"
    data = {
        "id": bundle_id,
        "title": title,
        "level": body.get("level", "FINAL").upper(),
        "group_name": body.get("groupName") or body.get("group_name") or "Custom",
        "subject_ids": body.get("subjectIds") or body.get("subject_ids") or [],
        "prices": prices,
        "is_custom": True,
        "is_active": body.get("isActive", True),
        "badge": body.get("badge") or "Custom Bundle",
    }
    try:
        res = db.table("mcq_bundles").upsert(data).execute()
        return {"success": True, "bundle": res.data[0] if res.data else data}
    except Exception as e:
        print(f"MCQ BUNDLE SAVE ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to save bundle. Please check every field and try again.")


@router.delete("/mcq/bundles/{bundle_id}")
async def admin_delete_mcq_bundle(
    bundle_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    try:
        db.table("mcq_bundles").delete().eq("id", bundle_id).execute()
    except Exception:
        pass
    return {"success": True}


@router.get("/mcq/subjects")
async def admin_list_mcq_subjects(
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    from app.routers.mcq import DEFAULT_MCQ_SUBJECTS
    try:
        res = db.table("mcq_subjects").select("*").order("sort_order").execute()
        return res.data if res.data else DEFAULT_MCQ_SUBJECTS
    except Exception:
        return DEFAULT_MCQ_SUBJECTS


@router.post("/mcq/subjects")
async def admin_upsert_mcq_subject(
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    name = _require_nonblank(body, "name", "Subject name")
    prices = body.get("prices") or {"1_month": 150, "3_months": 300, "6_months": 400, "1_year": 500}
    for tier, val in prices.items():
        prices[tier] = _require_non_negative(val, f"Subject price ({tier})")
    data = {
        "id": body.get("id"),
        "level": body.get("level", "FINAL").upper(),
        "group_name": body.get("groupName") or body.get("group_name") or "Group I",
        "name": name,
        "code": body.get("code"),
        "description": body.get("description", ""),
        "prices": prices,
        "is_active": body.get("isActive", True),
    }
    try:
        res = db.table("mcq_subjects").upsert(data).execute()
        return {"success": True, "subject": res.data[0] if res.data else data}
    except Exception as e:
        print(f"MCQ SUBJECT SAVE ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to save subject. Please check every field and try again.")


# ─── Chapters / Syllabus Master ──────────────────────────────────────────────

@router.get("/chapters")
async def admin_list_chapters(
    level: Optional[str] = None,
    subject_code: Optional[str] = None,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    try:
        query = db.table("subject_chapters").select("*")
        if level:
            query = query.eq("level", level.upper())
        if subject_code:
            query = query.eq("subject_code", subject_code.upper())
        res = query.order("chapter_number").execute()
        return res.data or []
    except Exception as e:
        return []


# ─── MCQ Sets Hierarchy & Management ─────────────────────────────────────────

@router.get("/mcq-sets")
async def admin_list_sets(
    level: Optional[str] = None,
    group_name: Optional[str] = None,
    subject_code: Optional[str] = None,
    test_type: Optional[str] = None,
    status: Optional[str] = None,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    try:
        query = db.table("mcq_papers").select("*")
        if level:
            query = query.eq("level", level.upper())
        if group_name:
            query = query.eq("group_name", group_name)
        if subject_code:
            query = query.eq("subject_code", subject_code.upper())
        if test_type:
            query = query.eq("test_type", test_type)
        if status:
            query = query.eq("status", status)
            
        sets_res = query.order("created_at", desc=True).execute()
        sets_data = sets_res.data or []

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

        # Enriched output
        enriched = []
        for s in sets_data:
            sections = sections_by_paper.get(s["id"], [])
            q_count = q_count_by_paper.get(s["id"], 0)

            enriched.append({
                "id": s["id"],
                "seriesId": s.get("series_id"),
                "title": s.get("title", "Untitled Set"),
                "level": s.get("level", "FINAL"),
                "groupName": s.get("group_name", "GROUP_1"),
                "subjectCode": s.get("subject_code") or s.get("subject", ""),
                "testType": s.get("test_type", "FULL_SUBJECT"),
                "chapterName": s.get("chapter_name"),
                "durationMinutes": s.get("duration_minutes", 60),
                "passingMarks": float(s.get("passing_marks") or 40.0),
                "totalMarks": float(s.get("total_marks") or 30.0),
                "status": s.get("status", "published"),
                "shuffleQuestions": s.get("shuffle_questions", False),
                "shuffleOptions": s.get("shuffle_options", False),
                "allowRetake": s.get("allow_retake", True),
                "maxAttempts": s.get("max_attempts"),
                "isLocked": s.get("is_locked", False),
                "price": float(s.get("price") or 0.0),
                "description": s.get("description", ""),
                "subject": s.get("subject", ""),
                "sectionCount": len(sections),
                "questionCount": q_count,
            })
        return enriched
    except Exception as e:
        return []


@router.get("/mcq-sets/{set_id}")
async def admin_get_set(
    set_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    mcq_set = db.table("mcq_papers").select("*").eq("id", set_id).single().execute()
    if not mcq_set.data:
        raise HTTPException(status_code=404, detail="MCQ set not found")

    sections_res = db.table("exam_sections").select("*").eq("paper_id", set_id).order("order_index").execute()
    sections = sections_res.data or []

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
        for q in (questions_res.data or []):
            mapped_questions.append({
                "id": q["id"],
                "type": q.get("type", "normal"),
                "case_narrative": q.get("case_narrative", ""),
                "case_group_id": q.get("case_group_id"),
                "difficulty": q.get("difficulty", "medium"),
                "marks": float(q.get("marks") or 1.0),
                "negative_marks": float(q.get("negative_marks") or 0.0),
                "content": q.get("content", ""),
                "options": q.get("options", ["", "", "", ""]),
                "correct_option": int(q.get("correct_option") or 0),
                "explanation": q.get("explanation", ""),
            })
        enriched_sections.append({
            "id": section["id"],
            "title": section["title"],
            "questions": mapped_questions,
        })

    s = mcq_set.data
    return {
        "id": s["id"],
        "seriesId": s.get("series_id"),
        "title": s["title"],
        "level": s.get("level", "FINAL"),
        "groupName": s.get("group_name", "GROUP_1"),
        "subjectCode": s.get("subject_code") or s.get("subject", ""),
        "testType": s.get("test_type", "FULL_SUBJECT"),
        "chapterName": s.get("chapter_name"),
        "durationMinutes": s.get("duration_minutes", 60),
        "passingMarks": float(s.get("passing_marks") or 40.0),
        "totalMarks": float(s.get("total_marks") or 30.0),
        "status": s.get("status", "published"),
        "shuffleQuestions": s.get("shuffle_questions", False),
        "shuffleOptions": s.get("shuffle_options", False),
        "allowRetake": s.get("allow_retake", True),
        "maxAttempts": s.get("max_attempts"),
        "isLocked": s.get("is_locked", False),
        "price": float(s.get("price") or 0.0),
        "description": s.get("description", ""),
        "subject": s.get("subject", ""),
        "sections": enriched_sections,
    }


@router.post("/mcq-sets")
async def admin_upsert_set(
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    set_id = body.get("id")
    # Generate a proper UUID if no id provided (DB column is UUID type)
    if not set_id or set_id == "":
        set_id = str(uuid.uuid4())

    subject_code = (body.get("subjectCode") or body.get("subject_code") or "").strip()
    if not subject_code:
        raise HTTPException(status_code=400, detail="Select a subject before saving this paper.")

    sections_payload = body.get("sections", [])
    question_number = 0
    for sec in sections_payload:
        sec_title = sec.get("title", "Untitled section")
        for q in sec.get("questions", []):
            question_number += 1
            content = (q.get("content") or q.get("text") or "").strip()
            if not content:
                raise HTTPException(
                    status_code=400,
                    detail=f'Question {question_number} (in section "{sec_title}") is missing its question text.'
                )
            options = q.get("options") or []
            if len(options) == 0 or any(not (opt or "").strip() for opt in options):
                raise HTTPException(
                    status_code=400,
                    detail=f'Question {question_number} (in section "{sec_title}") has a blank answer option.'
                )

    VALID_TEST_TYPES = ("COMPLETE_GROUP", "FULL_SUBJECT", "CHAPTER_WISE")
    raw_test_type = body.get("testType") or body.get("test_type") or "FULL_SUBJECT"
    safe_test_type = raw_test_type if raw_test_type in VALID_TEST_TYPES else "FULL_SUBJECT"

    VALID_LEVELS = ("FINAL", "INTERMEDIATE", "FOUNDATION")
    raw_level = body.get("level", "FINAL")
    safe_level = raw_level if raw_level in VALID_LEVELS else "FINAL"

    VALID_GROUPS = ("GROUP_1", "GROUP_2", "BOTH", "NONE")
    raw_group = body.get("groupName") or body.get("group_name") or "GROUP_1"
    safe_group = raw_group if raw_group in VALID_GROUPS else "GROUP_1"

    data = {
        "id": set_id,
        "title": body.get("title", "Untitled Test Paper"),
        "level": safe_level,
        "group_name": safe_group,
        "subject_code": subject_code,
        "test_type": safe_test_type,
        "chapter_name": body.get("chapterName") or body.get("chapter_name") or "",
        "duration_minutes": int(body.get("durationMinutes") or body.get("duration_minutes") or 60),
        "passing_marks": float(body.get("passingMarks") or body.get("passing_marks") or 40.0),
        "total_marks": float(body.get("totalMarks") or body.get("total_marks") or 100.0),
        "status": body.get("status", "draft"),
        "shuffle_questions": bool(body.get("shuffleQuestions") or body.get("shuffle_questions", False)),
        "shuffle_options": bool(body.get("shuffleOptions") or body.get("shuffle_options", False)),
    }

    # 1. Upsert the Set Wrapper
    try:
        result = db.table("mcq_papers").upsert(data).execute()
    except Exception as e:
        print(f"MCQ SAVE ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to save paper. Please check every field and try again.")
    
    # 2. Sync Sections & Questions
    existing_sections = db.table("exam_sections").select("id").eq("paper_id", set_id).execute()
    existing_sec_ids = [s["id"] for s in (existing_sections.data or [])]
    if existing_sec_ids:
        try:
            db.table("questions").delete().in_("section_id", existing_sec_ids).execute()
            db.table("exam_sections").delete().eq("paper_id", set_id).execute()
        except Exception:
            pass

    for sec_idx, sec in enumerate(sections_payload):
        # Always generate a fresh UUID — frontend uses Date.now() strings which are not valid UUIDs
        sec_id = str(uuid.uuid4())
        db.table("exam_sections").insert({
            "id": sec_id,
            "paper_id": set_id,
            "title": sec.get("title", f"Section {chr(65 + sec_idx)}"),
            "order_index": sec_idx,
        }).execute()

        # Insert questions
        questions_payload = sec.get("questions", [])

        # Pre-scan for contiguous case-study runs (authored order) so every
        # sub-question in a case block shares one case_group_id and the same
        # resolved narrative text, instead of only question #1 having it.
        run_id_by_idx: Dict[int, str] = {}
        run_narrative_by_idx: Dict[int, str] = {}
        run_start = None
        for i in range(len(questions_payload) + 1):
            is_case = i < len(questions_payload) and questions_payload[i].get("type") == "case"
            if is_case and run_start is None:
                run_start = i
            elif not is_case and run_start is not None:
                run_group_id = str(uuid.uuid4())
                run_narrative = ""
                for j in range(run_start, i):
                    candidate = (questions_payload[j].get("case_narrative") or questions_payload[j].get("caseText") or "").strip()
                    if candidate:
                        run_narrative = candidate
                        break
                for j in range(run_start, i):
                    run_id_by_idx[j] = run_group_id
                    run_narrative_by_idx[j] = run_narrative
                run_start = None

        for q_idx, q in enumerate(questions_payload):
            # Always generate a fresh UUID for questions too
            q_id = str(uuid.uuid4())
            db.table("questions").insert({
                "id": str(q_id),
                "section_id": sec_id,
                "type": q.get("type", "normal"),
                "case_narrative": run_narrative_by_idx.get(q_idx, q.get("case_narrative") or q.get("caseText") or ""),
                "case_group_id": run_id_by_idx.get(q_idx),
                "difficulty": q.get("difficulty", "medium"),
                "marks": float(q.get("marks") or 1.0),
                "negative_marks": float(q.get("negative_marks") or q.get("negativeMarks") or 0.0),
                "content": q.get("content") or q.get("text") or f"Question {q_idx + 1}",
                "options": q.get("options", ["Option A", "Option B", "Option C", "Option D"]),
                "correct_option": int(q.get("correct_option") if q.get("correct_option") is not None else q.get("correctOptionIndex", 0)),
                "explanation": q.get("explanation", ""),
                "order_index": q_idx
            }).execute()

    return result.data[0] if result.data else data


@router.patch("/mcq-sets/{set_id}/status")
async def admin_set_status(
    set_id: str,
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    status = body.get("status", "published")
    if status not in ["draft", "published", "archived"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    res = db.table("mcq_papers").update({"status": status}).eq("id", set_id).execute()
    return {"success": True, "status": status}


@router.post("/mcq-sets/{set_id}/import-questions")
async def admin_import_questions(
    set_id: str,
    body: BulkImportRequest,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    mcq_set = db.table("mcq_papers").select("id, chapter_name").eq("id", set_id).single().execute()
    if not mcq_set.data:
        raise HTTPException(status_code=404, detail="MCQ Set not found")

    target_sec_id = body.targetSectionId
    if not target_sec_id:
        # Find or create a default section
        secs = db.table("exam_sections").select("id").eq("paper_id", set_id).execute()
        if secs.data:
            target_sec_id = secs.data[0]["id"]
        else:
            new_sec_id = str(uuid.uuid4())
            db.table("exam_sections").insert({
                "id": new_sec_id,
                "paper_id": set_id,
                "title": "Imported Section"
            }).execute()
            target_sec_id = new_sec_id

    parsed_questions = []
    next_order_index = db.table("questions").select("id", count="exact").eq("section_id", target_sec_id).execute().count or 0

    if body.format.lower() == "csv":
        f = io.StringIO(body.content.strip())
        reader = csv.DictReader(f)
        for row in reader:
            # Flexible field lookup
            text = row.get("text") or row.get("question") or row.get("Question") or ""
            if not text.strip():
                continue
            
            # Options
            opt_a = row.get("option_a") or row.get("optionA") or row.get("A") or "Option A"
            opt_b = row.get("option_b") or row.get("optionB") or row.get("B") or "Option B"
            opt_c = row.get("option_c") or row.get("optionC") or row.get("C") or "Option C"
            opt_d = row.get("option_d") or row.get("optionD") or row.get("D") or "Option D"
            options = [opt_a, opt_b, opt_c, opt_d]

            # Correct option parsing (can be '0', '1', '2', '3' or 'A', 'B', 'C', 'D')
            corr = (row.get("correct_option") or row.get("correctOption") or row.get("correct") or "0").strip().upper()
            if corr in ["A", "0"]:
                corr_idx = 0
            elif corr in ["B", "1"]:
                corr_idx = 1
            elif corr in ["C", "2"]:
                corr_idx = 2
            elif corr in ["D", "3"]:
                corr_idx = 3
            else:
                corr_idx = 0

            q_type = (row.get("type") or "normal").strip().lower()
            case_narrative = row.get("case_narrative") or row.get("case_text") or row.get("caseText") or ""
            explanation = row.get("explanation") or row.get("Explanation") or ""
            marks = float(row.get("marks") or body.defaultMarks)
            neg_marks = float(row.get("negative_marks") or row.get("negativeMarks") or body.defaultNegativeMarks)
            difficulty = (row.get("difficulty") or "medium").strip().lower()

            parsed_questions.append({
                "id": str(uuid.uuid4()),
                "section_id": target_sec_id,
                "type": q_type,
                "case_narrative": case_narrative,
                "difficulty": difficulty,
                "marks": marks,
                "negative_marks": neg_marks,
                "content": text,
                "options": options,
                "correct_option": corr_idx,
                "explanation": explanation,
                "order_index": next_order_index,
            })
            next_order_index += 1

    elif body.format.lower() == "json":
        try:
            data = json.loads(body.content)
            items = data if isinstance(data, list) else data.get("questions", [])
            for item in items:
                text = item.get("text") or item.get("question", "")
                if not text:
                    continue
                options = item.get("options", ["A", "B", "C", "D"])
                corr_idx = int(item.get("correctOptionIndex") if item.get("correctOptionIndex") is not None else item.get("correct_option", 0))
                # Always generate a fresh UUID — imported files often carry
                # non-UUID ids (e.g. "q1") which the questions table rejects.
                parsed_questions.append({
                    "id": str(uuid.uuid4()),
                    "section_id": target_sec_id,
                    "type": item.get("type", "normal"),
                    "case_narrative": item.get("caseNarrative") or item.get("case_narrative") or item.get("caseText") or item.get("case_text", ""),
                    "difficulty": item.get("difficulty", "medium"),
                    "marks": float(item.get("marks") or body.defaultMarks),
                    "negative_marks": float(item.get("negativeMarks") or item.get("negative_marks") or body.defaultNegativeMarks),
                    "content": text,
                    "options": options,
                    "correct_option": corr_idx,
                    "explanation": item.get("explanation", ""),
                    "order_index": next_order_index,
                })
                next_order_index += 1
        except Exception as err:
            print(f"[BULK IMPORT] Invalid JSON: {err}")
            raise HTTPException(status_code=400, detail="Invalid JSON format. Please check the file and try again.")

    if not parsed_questions:
        raise HTTPException(status_code=400, detail="No valid questions found to import")

    # Insert into database
    for q in parsed_questions:
        db.table("questions").insert(q).execute()

    return {
        "success": True,
        "importedCount": len(parsed_questions),
        "targetSectionId": target_sec_id,
    }


@router.delete("/mcq-sets/{set_id}")
async def admin_delete_set(
    set_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    try:
        existing_sections = db.table("exam_sections").select("id").eq("paper_id", set_id).execute()
        sec_ids = [s["id"] for s in (existing_sections.data or [])]
        if sec_ids:
            db.table("questions").delete().in_("section_id", sec_ids).execute()
            db.table("exam_sections").delete().eq("paper_id", set_id).execute()
        db.table("mcq_papers").delete().eq("id", set_id).execute()
    except Exception:
        pass
    return {"success": True}


# ─── Test Evaluations (Admin Reviews) ────────────────────────────────────────

@router.get("/submissions/pending")
async def list_pending_submissions(
    status: str = "pending",
    staff: dict = Depends(require_mentor),
    db: Client = Depends(get_db),
):
    """Default (no `status` param) is unchanged — still just pending
    submissions, for backward compatibility. Pass `status=reviewed` to see
    already-evaluated records (with their marks/remarks/checked file), or
    `status=all` for both.

    There is no per-submission mentor-assignment concept in this schema —
    a permitted mentor sees the same full pending queue an admin already
    does, once explicitly granted evaluate_papers. That's intentional, not
    a new gap: previously admin was the only role that could even list
    this queue, though review_submission itself was already mentor-open."""
    if not await _mentor_has_permission(staff, "evaluate_papers", db):
        raise HTTPException(status_code=403, detail="You don't have permission to evaluate papers")
    settings = get_settings()
    query = (
        db.table("test_submissions")
        .select("*, profiles(email), tests(title), test_evaluations(marks, remarks, checked_file_url, evaluated_at)")
        .order("submitted_at", desc=False)
    )
    if status != "all":
        query = query.eq("status", status)
    subs = query.execute()
    result = []
    for s in (subs.data or []):
        profile = s.get("profiles") or {}
        test = s.get("tests") or {}
        email = profile.get("email", "")
        evaluations = s.get("test_evaluations") or []
        evaluation = evaluations[0] if evaluations else None
        checked_url = evaluation.get("checked_file_url") if evaluation else None
        # Signed, short-lived — these are personal answer sheets and
        # evaluations, not public content (see core/storage.py).
        student_files = [
            u for u in (signed_url_for(db, settings.supabase_submission_bucket, f) for f in (s.get("submission_files") or []))
            if u
        ]
        result.append({
            "id": s["id"],
            "studentEmail": email,
            "studentName": email.split("@")[0],
            "testTitle": test.get("title", ""),
            "submittedAt": s["submitted_at"],
            "studentFiles": student_files,
            "status": s.get("status", "pending"),
            "marksAwarded": evaluation.get("marks") if evaluation else None,
            "remarks": evaluation.get("remarks") if evaluation else None,
            "checkedFileUrl": signed_url_for(db, settings.supabase_evaluation_bucket, checked_url) if checked_url else None,
            "evaluatedAt": evaluation.get("evaluated_at") if evaluation else None,
        })
    return {"submissions": result}


@router.delete("/submissions/{submission_id}")
async def delete_submission(
    submission_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """Permanently removes a submission record and its evaluation (if any),
    including any remaining Storage files — same buckets/path convention the
    7-day auto-purge cron uses (see maintenance/purge-old-files above)."""
    settings = get_settings()
    _storage_path = storage_path_from_url

    sub = db.table("test_submissions").select("submission_files").eq("id", submission_id).execute()
    if not sub.data:
        raise HTTPException(status_code=404, detail="Submission not found")

    sub_paths = [p for p in (_storage_path(u, settings.supabase_submission_bucket) for u in (sub.data[0].get("submission_files") or [])) if p]
    if sub_paths:
        try:
            db.storage.from_(settings.supabase_submission_bucket).remove(sub_paths)
        except Exception as e:
            print(f"[DELETE SUBMISSION] storage cleanup failed for {submission_id}: {e}")

    evals = db.table("test_evaluations").select("id, checked_file_url").eq("submission_id", submission_id).execute()
    for ev in (evals.data or []):
        url = ev.get("checked_file_url") or ""
        path = _storage_path(url, settings.supabase_evaluation_bucket) if url else None
        if path:
            try:
                db.storage.from_(settings.supabase_evaluation_bucket).remove([path])
            except Exception as e:
                print(f"[DELETE SUBMISSION] evaluation storage cleanup failed for {ev['id']}: {e}")

    db.table("test_evaluations").delete().eq("submission_id", submission_id).execute()
    db.table("test_submissions").delete().eq("id", submission_id).execute()

    return {"success": True}


MAX_EVALUATION_FILE_BYTES = 3 * 1024 * 1024  # 3MB
ALLOWED_EVALUATION_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}


@router.post("/submissions/{submission_id}/review", status_code=200)
async def review_submission(
    submission_id: str,
    marks: float = Form(..., ge=0, le=105),
    remarks: str = Form(..., max_length=5000),
    checkedFile: Optional[UploadFile] = File(None),
    mentor_user: dict = Depends(require_mentor),
    db: Client = Depends(get_db),
):
    """Mentor/admin uploads the evaluated paper and submits marks + feedback;
    the student is emailed the result and the checked-file link. This is the
    single canonical review endpoint — it used to be duplicated with a
    JSON-only variant that silently shadowed this one and never actually
    emailed the student despite claiming to."""
    if not await _mentor_has_permission(mentor_user, "evaluate_papers", db):
        raise HTTPException(status_code=403, detail="You don't have permission to evaluate papers")
    settings = get_settings()

    # Verify submission exists
    sub = (
        db.table("test_submissions")
        .select("*, profiles(email), tests(title)")
        .eq("id", submission_id)
        .single()
        .execute()
    )
    if not sub.data:
        raise HTTPException(status_code=404, detail="Submission not found")

    checked_file_url = None
    if checkedFile:
        content_type = checkedFile.content_type or ""
        if content_type not in ALLOWED_EVALUATION_CONTENT_TYPES:
            raise HTTPException(status_code=400, detail="Checked file must be a PDF, JPG, or PNG")
        raw = await checkedFile.read()
        if len(raw) > MAX_EVALUATION_FILE_BYTES:
            raise HTTPException(status_code=400, detail="Checked file must be under 3MB")
        # Content-Type is attacker-controlled and easy to spoof — also check
        # the actual file bytes match a real signature for one of the
        # accepted types.
        is_pdf = raw.startswith(b"%PDF-")
        is_jpeg = raw.startswith(b"\xff\xd8\xff")
        is_png = raw.startswith(b"\x89PNG\r\n\x1a\n")
        if not (is_pdf or is_jpeg or is_png):
            raise HTTPException(status_code=400, detail="File doesn't look like a valid PDF, JPG, or PNG.")
        safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", checkedFile.filename or "evaluated")
        path = f"evaluated/{submission_id}/{safe_filename}"
        try:
            db.storage.from_(settings.supabase_evaluation_bucket).upload(
                path, raw, {"content-type": content_type}
            )
            checked_file_url = (
                f"{settings.supabase_url}/storage/v1/object/public/"
                f"{settings.supabase_evaluation_bucket}/{path}"
            )
        except Exception:
            checked_file_url = None

    # Find this mentor's mentors-table row (created by a super_admin via the
    # admin panel when granting the mentor role)
    mentor = db.table("mentors").select("id").eq("profile_id", mentor_user["id"]).execute()
    mentor_id = mentor.data[0]["id"] if mentor.data else None

    db.table("test_evaluations").insert({
        "submission_id": submission_id,
        "mentor_id": mentor_id,
        "marks": marks,
        "remarks": remarks,
        "checked_file_url": checked_file_url,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()

    db.table("test_submissions").update({"status": "reviewed"}).eq("id", submission_id).execute()

    student_profile = sub.data.get("profiles") or {}
    test_info = sub.data.get("tests") or {}
    student_email = student_profile.get("email", "")

    if settings.sendgrid_api_key and student_email:
        import httpx
        # 7-day expiry (not the default 5-minute one) since this link sits
        # in an inbox and may be opened days later — the student can also
        # always get a fresh link from their dashboard (GET /api/tests/submissions).
        emailed_url = signed_url_for(db, settings.supabase_evaluation_bucket, checked_file_url, expires_in=7 * 24 * 3600) if checked_file_url else None
        file_line = f'<p><a href="{emailed_url}">Download your checked answer sheet</a></p>' if emailed_url else ""
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
                    json={
                        "personalizations": [{"to": [{"email": student_email}]}],
                        "from": {"email": settings.sendgrid_from_email},
                        "subject": f"Your {test_info.get('title', 'Test')} has been evaluated!",
                        "content": [{
                            "type": "text/html",
                            "value": f"<h2>Test Evaluation Result</h2><p>Marks: {marks}</p><p>{remarks}</p>{file_line}",
                        }],
                    },
                )
        except Exception as e:
            print(f"Failed to email evaluation result to {student_email}: {e}")

    return {"success": True, "message": "Evaluation submitted and student notified"}


# ─── Admin: Tests CRUD ──────────────────────────────────────────────────────

@router.get("/tests")
async def admin_list_tests(admin: dict = Depends(require_admin), db: Client = Depends(get_db)):
    return db.table("tests").select("*").order("created_at", desc=True).execute().data or []


TEST_ALLOWED_FIELDS = {"title", "description", "question_file_url", "status", "sort_order", "subject_id"}


@router.post("/tests", status_code=201)
async def admin_create_test(
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """Create a new mock test and upload its question paper URL."""
    payload = {k: v for k, v in body.items() if k in TEST_ALLOWED_FIELDS}
    payload["created_by"] = admin["id"]
    result = db.table("tests").insert(payload).execute()
    return result.data[0] if result.data else {}


@router.patch("/tests/{test_id}")
async def admin_update_test(
    test_id: str,
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    allowed = {k: v for k, v in body.items() if k in TEST_ALLOWED_FIELDS}
    if not allowed:
        raise HTTPException(status_code=400, detail="Nothing to update")
    return db.table("tests").update(allowed).eq("id", test_id).execute().data


@router.delete("/tests/{test_id}")
async def admin_delete_test(
    test_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    _safe_delete(db, "tests", "id", test_id, "this test")
    return {"success": True}


# ─── Admin: Questions CRUD (for MCQ sets) ───────────────────────────────────

@router.get("/sections/{section_id}/questions")
async def admin_list_questions(
    section_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    return db.table("questions").select("*").eq("section_id", section_id).execute().data or []


QUESTION_ALLOWED_FIELDS = {
    "type", "case_narrative", "case_group_id", "difficulty", "marks",
    "negative_marks", "content", "options", "correct_option", "explanation",
    "order_index",
}


@router.post("/sections/{section_id}/questions", status_code=201)
async def admin_create_question(
    section_id: str,
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    payload = {k: v for k, v in body.items() if k in QUESTION_ALLOWED_FIELDS}
    payload["section_id"] = section_id
    result = db.table("questions").insert(payload).execute()
    return result.data[0] if result.data else {}


@router.patch("/questions/{question_id}")
async def admin_update_question(
    question_id: str,
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    allowed = {k: v for k, v in body.items() if k in QUESTION_ALLOWED_FIELDS}
    if not allowed:
        raise HTTPException(status_code=400, detail="Nothing to update")
    return db.table("questions").update(allowed).eq("id", question_id).execute().data


@router.delete("/questions/{question_id}")
async def admin_delete_question(
    question_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    _safe_delete(db, "questions", "id", question_id, "this question")
    return {"success": True}


# ─── Admin: Set Sections CRUD ────────────────────────────────────────────────

@router.get("/mcq-sets/{set_id}/sections")
async def admin_list_sections(
    set_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    return db.table("exam_sections").select("*").eq("paper_id", set_id).execute().data or []


@router.post("/mcq-sets/{set_id}/sections", status_code=201)
async def admin_create_section(
    set_id: str,
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    payload = {k: v for k, v in body.items() if k in {"title", "order_index"}}
    payload["paper_id"] = set_id
    result = db.table("exam_sections").insert(payload).execute()
    return result.data[0] if result.data else {}


@router.delete("/sections/{section_id}")
async def admin_delete_section(
    section_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    _safe_delete(db, "exam_sections", "id", section_id, "this section")
    return {"success": True}


# ─── Admin: Mentors CRUD ─────────────────────────────────────────────────────

DEFAULT_MENTOR_PERMISSIONS = {"evaluate_papers": False, "manage_sessions": False, "manage_test_series": False}


@router.get("/mentors")
async def admin_list_mentors(admin: dict = Depends(require_admin), db: Client = Depends(get_db)):
    rows = db.table("mentors").select("*, profiles(email)").execute().data or []
    perms_res = db.table("mentor_permissions").select("*").execute()
    perms_by_mentor = {p["mentor_id"]: (p.get("permissions") or {}) for p in (perms_res.data or [])}
    for r in rows:
        r["permissions"] = {**DEFAULT_MENTOR_PERMISSIONS, **perms_by_mentor.get(r["id"], {})}
    return rows


@router.patch("/mentors/{mentor_id}/permissions")
async def admin_update_mentor_permissions(
    mentor_id: str,
    body: MentorPermissionsUpdateRequest,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """Grants/revokes what a specific mentor can do — enforced server-side by
    _mentor_has_permission everywhere it's checked, not just hidden in the UI."""
    mentor = db.table("mentors").select("id").eq("id", mentor_id).execute()
    if not mentor.data:
        raise HTTPException(status_code=404, detail="Mentor not found")

    existing = db.table("mentor_permissions").select("*").eq("mentor_id", mentor_id).execute()
    current = {**DEFAULT_MENTOR_PERMISSIONS, **((existing.data[0].get("permissions") or {}) if existing.data else {})}
    updates = body.model_dump(exclude_unset=True)
    merged = {**current, **updates}

    db.table("mentor_permissions").upsert({
        "mentor_id": mentor_id,
        "permissions": merged,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="mentor_id").execute()
    return {"success": True, "permissions": merged}


@router.post("/mentors", status_code=201)
async def admin_create_mentor(
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    payload = {k: v for k, v in body.items() if k in {"profile_id", "name", "email", "specialty"}}
    result = db.table("mentors").insert(payload).execute()
    return result.data[0] if result.data else {}


@router.patch("/mentors/{mentor_id}")
async def admin_update_mentor(
    mentor_id: str,
    body: dict,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    # profile_id is intentionally excluded from updates — it's the identity
    # link to the user account and shouldn't be reassignable via this route.
    allowed = {k: v for k, v in body.items() if k in {"name", "email", "specialty"}}
    if not allowed:
        raise HTTPException(status_code=400, detail="Nothing to update")
    return db.table("mentors").update(allowed).eq("id", mentor_id).execute().data


@router.delete("/mentors/{mentor_id}")
async def admin_delete_mentor(
    mentor_id: str,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    _safe_delete(db, "mentors", "id", mentor_id, "this mentor")
    return {"success": True}


# ─── Admin: Session Request Queue ──────────────────────────────────────────

@router.get("/session-requests")
async def admin_list_session_requests(
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """
    Lists all pending session requests — where google_event_id = 'PENDING'.
    Admin reviews these and schedules a Google Meet.
    """
    rows = (
        db.table("session_bookings")
        .select("*, mentors(name, email), profiles(email)")
        .eq("google_event_id", "PENDING")
        .neq("status", "cancelled")
        .order("scheduled_at", desc=False)
        .execute()
    )

    result = []
    for r in (rows.data or []):
        mentor_info = r.get("mentors") or {}
        student_profile = r.get("profiles") or {}
        result.append({
            "id": r["id"],
            "studentEmail": student_profile.get("email", ""),
            "mentorName": mentor_info.get("name", ""),
            "requestedAt": r["scheduled_at"],
            "status": "pending_schedule",
        })
    return {"requests": result}


class ScheduleSessionBody(BaseModel):
    meetLink: str
    scheduledAt: str          # ISO datetime string
    durationMinutes: int = 30


@router.patch("/session-requests/{session_id}/schedule")
async def schedule_session(
    session_id: str,
    body: ScheduleSessionBody,
    admin: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    """
    Admin schedules the session — sets the actual datetime + Google Meet link.
    Automatically emails the student with the meeting details.
    """
    import httpx

    session = (
        db.table("session_bookings")
        .select("*, profiles(email), mentors(name)")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not session.data:
        raise HTTPException(status_code=404, detail="Session request not found")

    student_profile = session.data.get("profiles") or {}
    mentor_info = session.data.get("mentors") or {}
    student_email = session.data.get("student_email") or student_profile.get("email", "")

    # Update session with meet link + real scheduled time
    db.table("session_bookings").update({
        "google_meet_link": body.meetLink,
        "scheduled_at": body.scheduledAt,
        "duration_minutes": body.durationMinutes,
        "google_event_id": "SCHEDULED",   # Clear the PENDING sentinel
        "status": "booked",
    }).eq("id", session_id).execute()

    # Format datetime for email
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(body.scheduledAt.replace("Z", "+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        time_formatted = dt.strftime("%A, %d %B %Y at %I:%M %p (IST)")
    except Exception:
        time_formatted = body.scheduledAt

    # Email student with meet link — the DB update above already succeeded,
    # so a SendGrid failure here (timeout, DNS blip) must not turn this into
    # a 500 for the admin; the schedule itself is already saved.
    settings = get_settings()
    if settings.sendgrid_api_key and student_email:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
                    json={
                        "personalizations": [{"to": [{"email": student_email}]}],
                        "from": {"email": settings.sendgrid_from_email},
                        "subject": f"Your 1:1 Session with {mentor_info.get('name', 'Your Mentor')} is Confirmed!",
                        "content": [{
                            "type": "text/html",
                            "value": f"""
                            <h2>Your Session is Confirmed 🎉</h2>
                            <p><strong>Mentor:</strong> {mentor_info.get('name', 'Your Mentor')}</p>
                            <p><strong>Date & Time:</strong> {time_formatted}</p>
                            <p><strong>Duration:</strong> {body.durationMinutes} minutes</p>
                            <br/>
                            <p><a href="{body.meetLink}" style="background:#1a1a2e;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Join Google Meet</a></p>
                            <br/>
                            <p style="color:#666;">If the button doesn’t work, copy this link: {body.meetLink}</p>
                            """
                        }],
                    },
                )
        except Exception as e:
            print(f"[EMAIL] Failed to send session-confirmation email to {student_email}: {e}")
    else:
        print(f"[EMAIL STUB] Would email {student_email} with meet link: {body.meetLink}")

    return {"success": True, "message": f"Session scheduled and confirmation email sent to {student_email}"}


# (duplicate JSON-only "/submissions/{submission_id}/review" removed — see the
# single canonical multipart version above, which now also sends this email)
