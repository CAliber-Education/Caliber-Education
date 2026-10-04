import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Optional
import uuid

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from postgrest.exceptions import APIError as PostgrestAPIError
from supabase import Client

from app.core.config import get_settings
from app.core.database import get_db
from app.core.email import send_email
from app.core.limiter import limiter
from app.dependencies import get_current_user, require_admin
from app.schemas.payments import CreateOrderRequest, VerifyPaymentRequest
from app.routers import scholarship
from app.routers.mcq import calculate_mcq_cart
from app.routers.test_series import calculate_test_series_cart

router = APIRouter(prefix="/api/payments", tags=["Payments"])


class CreateMCQOrderRequest(BaseModel):
    level: str
    subjectIds: list[str]
    duration: str = "1_month"
    couponCode: Optional[str] = None


class CreateScholarshipOrderRequest(BaseModel):
    paperId: str
    couponCode: Optional[str] = None


class CreateTestSeriesOrderRequest(BaseModel):
    level: str
    subjectIds: list[str]
    couponCode: Optional[str] = None


def _get_razorpay_client():
    settings = get_settings()
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        return None
    return razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )


def _resolve_coupon(db: Client, coupon_code: Optional[str], course_id: str, user_id: str, price: float):
    """
    Central coupon resolution logic — returns (coupon_row, discount_amount, affiliate_id, commission_amount)
    or (None, 0, None, 0) if no valid coupon.
    """
    if not coupon_code:
        return None, 0.0, None, 0.0

    code = coupon_code.strip().upper()
    result = db.table("coupons").select("*").eq("code", code).execute()
    if not result.data:
        return None, 0.0, None, 0.0

    coupon = result.data[0]

    # Active check
    if not coupon.get("is_active"):
        return None, 0.0, None, 0.0

    # Validity window
    now = datetime.now(timezone.utc)
    if coupon.get("valid_from"):
        vf = datetime.fromisoformat(coupon["valid_from"].replace("Z", "+00:00"))
        if vf.tzinfo is None: vf = vf.replace(tzinfo=timezone.utc)
        if now < vf:
            return None, 0.0, None, 0.0
    if coupon.get("valid_until"):
        vu = datetime.fromisoformat(coupon["valid_until"].replace("Z", "+00:00"))
        if vu.tzinfo is None: vu = vu.replace(tzinfo=timezone.utc)
        if now > vu:
            return None, 0.0, None, 0.0

    # Max uses
    if coupon.get("max_uses") is not None and coupon["used_count"] >= coupon["max_uses"]:
        return None, 0.0, None, 0.0

    # Per-user
    max_per_user = coupon.get("max_uses_per_user", 1)
    usage = (
        db.table("coupon_usages")
        .select("id", count="exact")
        .eq("coupon_id", coupon["id"])
        .eq("user_id", user_id)
        .execute()
    )
    if (usage.count or 0) >= max_per_user:
        return None, 0.0, None, 0.0

    # Course applicability
    applicable = coupon.get("applicable_course_ids") or []
    if applicable and course_id not in applicable:
        return None, 0.0, None, 0.0

    # Compute discount
    if coupon["discount_type"] == "percent":
        discount_amount = round(min(price, price * float(coupon["discount_value"]) / 100), 2)
    else:
        discount_amount = round(min(price, float(coupon["discount_value"])), 2)

    # Compute commission if affiliate-linked
    affiliate_id = coupon.get("affiliate_id")
    commission_amount = 0.0
    if affiliate_id:
        aff = db.table("affiliates").select("*").eq("id", affiliate_id).execute()
        if aff.data:
            affiliate = aff.data[0]
            final_price = price - discount_amount
            if affiliate["commission_type"] == "percent":
                commission_amount = round(final_price * float(affiliate["commission_value"]) / 100, 2)
            else:
                commission_amount = round(min(final_price, float(affiliate["commission_value"])), 2)

    return coupon, discount_amount, affiliate_id, commission_amount


def _record_coupon_usage(
    db: Client, coupon: dict, user_id: str, payment_id: str,
    discount_amount: float, affiliate_id: Optional[str], commission_amount: float,
):
    """
    After successful payment: log the coupon usage, bump used_count,
    and tag the payment with coupon/affiliate data.
    Idempotent — checks if usage already exists.
    """
    # Check idempotency
    existing = (
        db.table("coupon_usages")
        .select("id")
        .eq("coupon_id", coupon["id"])
        .eq("user_id", user_id)
        .execute()
    )
    if existing.data:
        return  # Already recorded — don't double-count

    # Log usage
    db.table("coupon_usages").insert({
        "coupon_id": coupon["id"],
        "user_id": user_id,
        "payment_id": payment_id,
    }).execute()

    # Bump used_count on the coupon
    db.table("coupons").update({
        "used_count": coupon["used_count"] + 1,
    }).eq("id", coupon["id"]).execute()

    # Tag payment row with coupon + affiliate info
    db.table("payments").update({
        "coupon_id": coupon["id"],
        "discount_amount": discount_amount,
        "affiliate_id": affiliate_id,
        "commission_amount": commission_amount,
    }).eq("id", payment_id).execute()


@router.post("/create-order", status_code=201)
@limiter.limit("10/minute")
async def create_order(
    request: Request,
    body: CreateOrderRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    settings = get_settings()

    # Check if a bundle was mapped. course_bundles.id is a uuid column, but
    # regular course purchases pass a text slug — querying it with a
    # non-uuid string throws a Postgres cast error (22P02), not an empty
    # result, so this only queries when courseId actually looks like a uuid.
    bundle = None
    if body.courseId:
        try:
            uuid.UUID(body.courseId)
            bundle = db.table("course_bundles").select("id, title, price, course_ids").eq("id", body.courseId).execute()
        except ValueError:
            bundle = None

    is_bundle = False
    is_multi_course_cart = False
    original_price = 0.0

    if bundle and bundle.data:
        is_bundle = True
        price = float(bundle.data[0].get("price") or 0)
        original_price = price
        active_course_id = body.courseId
    elif body.courseIds and len(body.courseIds) > 0:
        is_multi_course_cart = True
        # Custom checkout cart with multiple item IDs directly passed from BundleBuilder
        courses_res = db.table("courses").select("id, title, price").in_("id", body.courseIds).execute()
        if not courses_res.data:
            raise HTTPException(status_code=404, detail="Items not found in database")
        price = sum(float(c.get("price") or 0) for c in courses_res.data)
        original_price = price
        # Only used for Razorpay's receipt/notes below and for coupon
        # applicability matching — the actual `payments` row can't store this
        # (comma-joined, not a real course id) since course_id has a foreign
        # key to courses.id. See the packed utr_number below instead.
        active_course_id = ",".join(body.courseIds)
    else:
        # Fetch standard course price and metadata
        course = db.table("courses").select("id, title, price, whatsapp_link").eq("id", body.courseId).single().execute()
        if not course.data:
            raise HTTPException(status_code=404, detail="Item not found")
        price = float(course.data.get("price") or 0)
        original_price = price
        active_course_id = body.courseId

    # Resolve coupon server-side
    coupon, discount_amount, affiliate_id, commission_amount = _resolve_coupon(
        db, body.couponCode, active_course_id, current_user["id"], price
    )

    final_price = max(0, price - discount_amount)
    amount_paise = int(final_price * 100)

    rzp = _get_razorpay_client()
    if rzp:
        try:
            order = rzp.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"course_{active_course_id[:20]}",
                "notes": {
                    "course_id": active_course_id,
                    "user_id": current_user["id"],
                    "coupon_code": coupon["code"] if coupon else "",
                },
            })
            order_id = order["id"]
        except Exception as e:
            print(f"[PAYMENTS] Razorpay order creation failed: {e}")
            raise HTTPException(status_code=502, detail="Couldn't start payment. Please try again in a moment.")
    else:
        # Stub for dev/testing without Razorpay keys
        order_id = f"order_DEMO_{uuid.uuid4().hex[:12].upper()}"

    # Insert pending payment record with coupon metadata. A multi-course cart
    # can't store its comma-joined id list in course_id (foreign key to
    # courses.id would reject it) — same reason the MCQ/test-series order
    # endpoints below pack their item list into utr_number with course_id
    # left NULL instead.
    payment_row = {
        "user_id": current_user["id"],
        "course_id": None if is_multi_course_cart else active_course_id,
        "amount": final_price,
        "original_amount": original_price,
        "discount_amount": discount_amount,
        "coupon_id": coupon["id"] if coupon else None,
        "affiliate_id": affiliate_id,
        "commission_amount": commission_amount,
        "status": "pending",
        "razorpay_order_id": order_id,
    }
    if is_multi_course_cart:
        payment_row["utr_number"] = "courses|" + ",".join(body.courseIds) + f"|{uuid.uuid4().hex[:8]}"
    db.table("payments").insert(payment_row).execute()

    return {
        "orderId": order_id,
        "amount": amount_paise,
        "currency": "INR",
        "key": settings.razorpay_key_id or "rzp_test_demo",
        "originalAmount": int(original_price * 100),
        "discountAmount": int(discount_amount * 100),
        "couponCode": coupon["code"] if coupon else None,
    }


@router.post("/mock-confirm")
async def mock_confirm(
    body: VerifyPaymentRequest,
    current_user: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    settings = get_settings()
    if os.getenv("ALLOW_TEST_PAYMENTS", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Test payments are currently disabled.")

    # Check what type of order it is
    payment = (
        db.table("payments")
        .select("*")
        .eq("razorpay_order_id", body.razorpay_order_id)
        .eq("user_id", current_user["id"])
        .single()
        .execute()
    )
    if not payment.data:
        raise HTTPException(status_code=404, detail="Test payment record not found")

    # Call the exact same logic as verify_payment mapping
    return await _apply_course_grant_or_extend(db, payment.data, current_user["id"], current_user.get("email"), body.razorpay_payment_id, "mock_signature", settings)


@router.post("/verify-payment")
@limiter.limit("20/minute")
async def verify_payment(
    request: Request,
    body: VerifyPaymentRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    settings = get_settings()
    user_id = current_user["id"]

    # Verify HMAC-SHA256 signature natively with Razorpay SDK. Fails closed
    # if the secret isn't configured — a missing secret must never be
    # silently treated as "verified" (a prior "pay_TEST_"/"order_DEMO_"
    # prefix bypass here let any caller forge those IDs and get free
    # enrollment; removed).
    if not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured. Please contact support.")
    rzp = _get_razorpay_client()
    try:
        params_dict = {
            'razorpay_order_id': body.razorpay_order_id,
            'razorpay_payment_id': body.razorpay_payment_id,
            'razorpay_signature': body.razorpay_signature
        }
        rzp.utility.verify_payment_signature(params_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    payment = (
        db.table("payments")
        .select("*")
        .eq("razorpay_order_id", body.razorpay_order_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not payment.data:
        raise HTTPException(status_code=404, detail="Payment record not found")

    return await _apply_course_grant_or_extend(db, payment.data, user_id, current_user.get("email"), body.razorpay_payment_id, body.razorpay_signature, settings)


async def _apply_course_grant_or_extend(db: Client, payment_data: dict, user_id: str, email: str, rzp_pay_id: str, rzp_sig: str, settings):
    course_id = payment_data.get("course_id")
    payment_id = payment_data["id"]

    # Idempotency guard: a replayed/retried verify call for a payment already
    # marked approved must not re-run the grant logic a second time — this
    # mirrors the check the webhook handler already applies before dispatching.
    if payment_data.get("status") == "approved":
        return {"success": True, "message": "Payment already verified and enrollment already completed."}

    # Multi-course cart purchases store course_id as NULL (a comma-joined id
    # list can't satisfy the foreign key to courses.id) and pack the real
    # course ids into utr_number instead — see create_order's insert.
    utr = payment_data.get("utr_number") or ""
    packed_course_ids = None
    if course_id is None and utr.startswith("courses|"):
        packed_course_ids = [c.strip() for c in utr.split("|", 2)[1].split(",") if c.strip()]

    bundle = None
    if course_id:
        try:
            uuid.UUID(course_id)
            bundle = db.table("course_bundles").select("id, course_ids").eq("id", course_id).execute()
        except ValueError:
            bundle = None
    custom_whatsapp_links = []

    course_titles = []

    # Grant the actual course access first — only once every extend call
    # below has succeeded do we mark the payment "approved". A failure here
    # raises and propagates to the caller, leaving the payment "pending" so
    # a retry (webhook redelivery, a manual re-verify) can complete it,
    # rather than the payment silently looking approved with nothing granted.
    if (bundle and bundle.data) or packed_course_ids or (course_id and "," in course_id):
        if bundle and bundle.data:
            c_ids = bundle.data[0].get("course_ids", [])
        elif packed_course_ids is not None:
            c_ids = packed_course_ids
        else:
            c_ids = course_id.split(",")
        for cid in c_ids:
            if not cid.strip(): continue
            _atomic_extend_course(db, user_id, cid.strip(), payment_id)
            cdata = db.table("courses").select("whatsapp_link, title").eq("id", cid.strip()).execute()
            if cdata.data and len(cdata.data) > 0:
                if cdata.data[0].get("whatsapp_link"):
                    custom_whatsapp_links.append(cdata.data[0].get("whatsapp_link"))
                if cdata.data[0].get("title"):
                    course_titles.append(cdata.data[0].get("title"))
            _apply_course_extras(db, user_id, cid.strip(), payment_id)
    else:
        _atomic_extend_course(db, user_id, course_id, payment_id)
        course_data = db.table("courses").select("whatsapp_link, title").eq("id", course_id).single().execute()
        if course_data.data:
            if course_data.data.get("whatsapp_link"):
                custom_whatsapp_links.append(course_data.data.get("whatsapp_link"))
            if course_data.data.get("title"):
                course_titles.append(course_data.data.get("title"))
        _apply_course_extras(db, user_id, course_id, payment_id)

    db.table("payments").update({
        "status": "approved",
        "razorpay_payment_id": rzp_pay_id,
        "razorpay_signature": rzp_sig,
    }).eq("id", payment_id).execute()

    coupon_id = payment_data.get("coupon_id")
    if coupon_id:
        coupon_row = db.table("coupons").select("*").eq("id", coupon_id).single().execute()
        if coupon_row.data:
            _record_coupon_usage(
                db, coupon_row.data, user_id, payment_id,
                float(payment_data.get("discount_amount") or 0),
                payment_data.get("affiliate_id"),
                float(payment_data.get("commission_amount") or 0),
            )

    if email:
        try:
            names = ", ".join(course_titles) if course_titles else "your course"
            await send_email(
                to_email=email,
                subject="Payment confirmed — Caliber Education",
                html_content=(
                    f"<p>Hi,</p><p>Your payment has been verified and you now have access to "
                    f"<strong>{names}</strong>.</p><p>Log in to your dashboard to get started.</p>"
                ),
            )
        except Exception as e:
            print(f"[EMAIL] Failed to send course purchase confirmation to {email}: {e}")

    return {"success": True, "message": "Payment verified and enrollment completed/extended."}


def grant_test_series_subjects(db: Client, user_id: str, subject_ids: list, payment_id: str | None = None):
    """Idempotent insert-if-not-exists grant of test-series subject access for
    one user. Shared by the purchase-time flow (_apply_course_extras below)
    and the admin retroactive-grant flow (admin.py, when a course's bundled
    subject list is edited after the fact)."""
    for sub_id in (subject_ids or []):
        sub_id = (sub_id or "").strip()
        if not sub_id:
            continue
        try:
            existing = (
                db.table("test_series_enrollments").select("id")
                .eq("user_id", user_id).eq("subject_id", sub_id).execute()
            )
            if not existing.data:
                db.table("test_series_enrollments").insert({
                    "user_id": user_id,
                    "subject_id": sub_id,
                    "payment_id": payment_id,
                    "access_until": None,
                }).execute()
                print(f"[EXTRAS] Granted test series {sub_id} to {user_id}")
        except Exception as e:
            print(f"[EXTRAS] Failed granting test series {sub_id}: {e}")


def _apply_course_extras(db: Client, user_id: str, course_id: str, payment_id: str):
    """After a course purchase, grant anything bundled with it:
      • test-series subjects attached by the admin to that course
      • a 1:1 session booking, if the course is a 1:1 product
    Both are no-ops for plain WhatsApp/mentorship courses."""
    try:
        c = db.table("courses").select(
            "bundled_test_series_subject_ids, is_one_on_one"
        ).eq("id", course_id).single().execute()
    except Exception as e:
        print(f"[EXTRAS] Could not read course {course_id}: {e}")
        return
    if not c.data:
        return

    # 1. Bundled test series
    grant_test_series_subjects(db, user_id, c.data.get("bundled_test_series_subject_ids") or [], payment_id)

    # 2. 1:1 session booking — created unassigned; admin picks the mentor next
    if c.data.get("is_one_on_one"):
        try:
            already = (
                db.table("session_bookings").select("id")
                .eq("payment_id", payment_id).execute()
            )
            if not already.data:
                db.table("session_bookings").insert({
                    "student_id": user_id,
                    "course_id": course_id,
                    "payment_id": payment_id,
                    "status": "pending_assignment",
                }).execute()
                print(f"[EXTRAS] Created 1:1 session booking for {user_id} ({course_id})")
        except Exception as e:
            print(f"[EXTRAS] Failed creating session booking: {e}")


def _atomic_extend_course(db: Client, user_id: str, course_id: str, payment_id: str):
    base_duration = 90
    course_data = db.table("courses").select("duration").eq("id", course_id).execute()
    if course_data.data and len(course_data.data) > 0:
        d = course_data.data[0].get("duration") or ""
        if "6 month" in d.lower(): base_duration = 180
        elif "1 year" in d.lower(): base_duration = 365
    
    # No try/except here on purpose — this is the actual course-access grant.
    # A failure must propagate to the caller so the payment is never marked
    # "approved" while the customer received nothing (see
    # _apply_course_grant_or_extend, which only flips status to "approved"
    # after every extend call here has succeeded).
    db.rpc("grant_or_extend_enrollment", {
        "p_user_id": user_id,
        "p_course_id": course_id,
        "p_duration_days": base_duration
    }).execute()


# ─── MCQ Package Payment Endpoints ──────────────────────────────────────────

@router.post("/create-mcq-order", status_code=201)
@limiter.limit("10/minute")
async def create_mcq_order(
    request: Request,
    body: CreateMCQOrderRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    settings = get_settings()
    if not body.subjectIds:
        raise HTTPException(status_code=400, detail="No subjects selected")

    calc = calculate_mcq_cart(body.level, body.subjectIds, body.duration, db)
    base_price = calc["real_total_price"]
    discounted_price = calc["discounted_price"]

    # Resolve optional coupon on top of bundle price if provided
    coupon, coupon_discount, affiliate_id, commission_amount = _resolve_coupon(
        db, body.couponCode, f"mcq-{body.level.lower()}", current_user["id"], discounted_price
    )

    final_price = max(0.0, discounted_price - coupon_discount)
    amount_paise = int(final_price * 100)

    rzp = _get_razorpay_client()
    if rzp:
        try:
            order = rzp.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"mcq_{body.level[:5].lower()}_{body.duration}",
                "notes": {
                    "type": "mcq_package",
                    "level": body.level,
                    "duration": body.duration,
                    "subject_ids": ",".join(body.subjectIds),
                    "user_id": current_user["id"],
                    "bundle_id": calc.get("applied_bundle_id") or "",
                },
            })
            order_id = order["id"]
        except Exception as e:
            print(f"Razorpay API Error during MCQ order, falling back to dummy ID: {e}")
            order_id = f"order_MCQ_FALLBACK_{uuid.uuid4().hex[:8].upper()}"
    else:
        order_id = f"order_MCQ_{uuid.uuid4().hex[:12].upper()}"

    # Record payment row
    try:
        db.table("payments").insert({
            "user_id": current_user["id"],
            "course_id": None, # Cannot use course_id due to foreign key constraint to courses table
            "utr_number": f"mcq-{body.level.lower()}-{body.duration}|" + ",".join(body.subjectIds) + f"|{uuid.uuid4().hex[:8]}",
            "amount": final_price,
            "original_amount": base_price,
            "discount_amount": base_price - final_price,
            "coupon_id": coupon["id"] if coupon else None,
            "affiliate_id": affiliate_id,
            "commission_amount": commission_amount,
            "status": "pending",
            "razorpay_order_id": order_id
        }).execute()
    except Exception as e:
        print("Error inserting payment:", e)
        pass

    return {
        "orderId": order_id,
        "amount": amount_paise,
        "currency": "INR",
        "key": settings.razorpay_key_id or "rzp_test_demo",
        "originalAmount": int(base_price * 100),
        "discountAmount": int((base_price - final_price) * 100),
        "finalAmount": int(final_price * 100),
        "savingsAmount": calc["savings_amount"],
        "appliedBundle": calc.get("applied_bundle_title"),
        "couponCode": coupon["code"] if coupon else None,
    }


def _scholarship_checkout(db: Client, paper_id: str, user_id: str, coupon_code: Optional[str]) -> dict:
    """Price and payment row for one Scholarship Test registration. The
    grant goes through _apply_mcq_grant like any MCQ purchase ("mcq-" utr),
    as a lifetime mcq_enrollments row for scholarship.access_code(paper)."""
    rows = db.table("mcq_papers").select("*").eq("id", paper_id).execute().data or []
    paper = rows[0] if rows else None
    if not scholarship.is_scholarship(paper) or paper.get("status") != "published":
        raise HTTPException(status_code=404, detail="This Scholarship Test isn't open.")
    if scholarship.is_closed(paper):
        raise HTTPException(status_code=404, detail="This Scholarship Test is closed — its results are out.")
    price = float(paper.get("price") or 0)
    if price <= 0:
        raise HTTPException(status_code=400, detail="This Scholarship Test has no price set yet.")
    if scholarship.has_access(db, user_id, paper_id):
        raise HTTPException(status_code=409, detail="You're already registered for this test.")
    coupon, coupon_discount, affiliate_id, commission_amount = _resolve_coupon(
        db, coupon_code, "mcq-scholarship", user_id, price
    )
    final_price = max(0.0, price - coupon_discount)
    return {
        "paper": paper,
        "price": price,
        "final_price": final_price,
        "coupon": coupon,
        "row": {
            "user_id": user_id,
            "course_id": None,
            # "lifetime": _apply_mcq_grant gives no expiry for an unknown duration.
            "utr_number": f"mcq-scholarship-lifetime|{scholarship.access_code(paper_id)}|{uuid.uuid4().hex[:8]}",
            "amount": final_price,
            "original_amount": price,
            "discount_amount": price - final_price,
            "coupon_id": coupon["id"] if coupon else None,
            "affiliate_id": affiliate_id,
            "commission_amount": commission_amount,
            "status": "pending",
        },
    }


@router.post("/create-scholarship-order", status_code=201)
@limiter.limit("10/minute")
async def create_scholarship_order(
    request: Request,
    body: CreateScholarshipOrderRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    settings = get_settings()
    co = _scholarship_checkout(db, body.paperId, current_user["id"], body.couponCode)
    amount_paise = int(round(co["final_price"] * 100))
    rzp = _get_razorpay_client()
    if rzp:
        try:
            order = rzp.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"scholar_{body.paperId[:20]}",
                "notes": {"type": "scholarship_test", "paper_id": body.paperId, "user_id": current_user["id"]},
            })
            order_id = order["id"]
        except Exception as e:
            print(f"Razorpay API Error during scholarship order, falling back to dummy ID: {e}")
            order_id = f"order_SCH_FALLBACK_{uuid.uuid4().hex[:8].upper()}"
    else:
        order_id = f"order_SCH_{uuid.uuid4().hex[:12].upper()}"
    db.table("payments").insert({**co["row"], "razorpay_order_id": order_id}).execute()
    return {
        "orderId": order_id,
        "amount": amount_paise,
        "currency": "INR",
        "key": settings.razorpay_key_id or "rzp_test_demo",
        "originalAmount": int(round(co["price"] * 100)),
        "finalAmount": amount_paise,
        "couponCode": co["coupon"]["code"] if co["coupon"] else None,
    }


@router.post("/mock-confirm-mcq")
async def mock_confirm_mcq(
    body: VerifyPaymentRequest,
    current_user: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    if os.getenv("ALLOW_TEST_PAYMENTS", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Test payments are currently disabled.")

    return await _apply_mcq_grant(db, body.razorpay_order_id, current_user["id"], "pay_TEST_MCQ", "mock_signature")


@router.post("/verify-mcq-payment")
@limiter.limit("20/minute")
async def verify_mcq_payment(
    request: Request,
    body: VerifyPaymentRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    settings = get_settings()

    # Fails closed if the secret isn't configured — see verify-payment's
    # comment above; same client-controlled bypass removed here.
    if not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured. Please contact support.")
    rzp = _get_razorpay_client()
    try:
        params_dict = {
            'razorpay_order_id': body.razorpay_order_id,
            'razorpay_payment_id': body.razorpay_payment_id,
            'razorpay_signature': body.razorpay_signature
        }
        rzp.utility.verify_payment_signature(params_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    result = await _apply_mcq_grant(db, body.razorpay_order_id, current_user["id"], body.razorpay_payment_id, body.razorpay_signature)
    # The frontend only checks the HTTP status to decide success/failure, not
    # this body — a grant failure must not come back as a 200, or a genuine
    # signature-verified-but-unmatched-order request would show as "paid."
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Payment record not found"))
    return result


async def _apply_mcq_grant(db: Client, order_id: str, user_id: str, rzp_pay: str, rzp_sig: str):

    # Scoped to the caller — without this, anyone who learns another
    # user's order_id (order IDs plus the public key are enough to open
    # a checkout for that specific order) could pay for and claim that
    # order's grant for themselves instead of its actual owner.
    payment = db.table("payments").select("*").eq("razorpay_order_id", order_id).eq("user_id", user_id).execute()
    if not payment.data:
        # No matching payment for this order+user — either a bad
        # order_id or (post-fix) someone else's order. Previously this
        # fell through with no explicit return and still reported
        # success at the bottom of this function despite granting
        # nothing; now it fails the same way _apply_test_series_grant
        # already correctly does.
        return {"success": False, "message": "No matching payment found"}

    payment_row = payment.data[0]
    payment_id = payment_row["id"]

    # Idempotency guard: a replayed/retried verify call for a payment
    # already marked approved must not re-run the grant a second
    # time (it would stack additional access time onto the
    # enrollment) — mirrors the check the webhook handler already
    # applies before dispatching.
    if payment_row.get("status") == "approved":
        return {"success": True, "message": "MCQ package already activated."}

    # Grant the actual mcq_enrollments based on the subjects packed into
    # utr_number (separated by |) BEFORE marking the payment approved. No
    # try/except swallowing here on purpose — a failure must propagate so
    # the payment stays "pending" and a retry can actually complete the
    # grant, instead of the payment looking "approved" with nothing
    # delivered and no way to automatically recover.
    packed_course_id = payment_row.get("utr_number", "")
    if "|" in packed_course_id:
        base_c_id, raw_subjects = packed_course_id.split("|", 1)
        if "|" in raw_subjects:
            raw_subjects = raw_subjects.split("|")[0]
        duration_str = base_c_id.split("-")[-1] if "-" in base_c_id else "1_month"

        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        expiry = None
        if duration_str == "1_month": expiry = (now + timedelta(days=30)).isoformat()
        elif duration_str == "3_months": expiry = (now + timedelta(days=90)).isoformat()
        elif duration_str == "6_months": expiry = (now + timedelta(days=180)).isoformat()
        elif duration_str == "1_year": expiry = (now + timedelta(days=365)).isoformat()

        subjects_list = raw_subjects.split(",")
        for sub_id in subjects_list:
            sub_id = sub_id.strip()
            print(f"[MCQ ENROLL] Processing subject: {sub_id}, duration: {duration_str}")

            # Check if enrollment already exists
            existing_enroll = db.table("mcq_enrollments")\
                .select("id, access_until")\
                .eq("user_id", user_id)\
                .eq("subject_code", sub_id)\
                .execute()

            if existing_enroll.data:
                # Pick the row with the latest access_until
                def parse_dt(s):
                    if not s: return datetime(2000, 1, 1, tzinfo=timezone.utc)
                    try:
                        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return dt
                    except ValueError:
                        return datetime(2000, 1, 1, tzinfo=timezone.utc)

                best_row = max(existing_enroll.data, key=lambda r: parse_dt(r.get("access_until")))
                existing_row_id = best_row["id"]
                existing_expiry_str = best_row.get("access_until")
                print(f"[MCQ ENROLL] Existing expiry for {sub_id}: {existing_expiry_str}")

                existing_expiry = parse_dt(existing_expiry_str)
                # Stack extension on top of existing expiry (if future) or from now (if expired)
                base_date = existing_expiry if existing_expiry > now else now

                if duration_str == "1_month":    new_expiry = (base_date + timedelta(days=30)).isoformat()
                elif duration_str == "3_months": new_expiry = (base_date + timedelta(days=90)).isoformat()
                elif duration_str == "6_months": new_expiry = (base_date + timedelta(days=180)).isoformat()
                elif duration_str == "1_year":   new_expiry = (base_date + timedelta(days=365)).isoformat()
                else:                            new_expiry = (base_date + timedelta(days=30)).isoformat()

                # Plain ASCII "->" on purpose, not "→" — a non-ASCII character
                # here crashes with UnicodeEncodeError on any stdout that
                # isn't UTF-8 (e.g. a default Windows console), and since the
                # grant loop no longer swallows exceptions (see the comment
                # a few lines up), that crash used to abort the entire grant
                # — the actual root cause behind the duplicate-enrollment
                # test data this was found from.
                print(f"[MCQ ENROLL] Extending {sub_id}: {existing_expiry_str} + {duration_str} -> {new_expiry}")

                # Update ONLY the latest row for this subject
                db.table("mcq_enrollments").update({
                    "access_until": new_expiry,
                    "payment_id": payment_id,
                }).eq("id", existing_row_id).execute()
            else:
                print(f"[MCQ ENROLL] New enrollment for {sub_id}, expiry: {expiry}")
                try:
                    db.table("mcq_enrollments").insert({
                        "user_id": user_id,
                        "subject_code": sub_id,
                        "level": base_c_id.split("-")[1].upper() if len(base_c_id.split("-")) > 1 else "FINAL",
                        "payment_id": payment_id,
                        "access_until": expiry
                    }).execute()
                except PostgrestAPIError as e:
                    # 23505 = unique_violation — a concurrent request (double-
                    # click, webhook racing this same call) already inserted
                    # the identical (user_id, subject_code) enrollment a
                    # moment ago. That request already granted the access
                    # this one was trying to grant, so this is a benign
                    # no-op, not a real failure — anything else re-raises.
                    if e.code != "23505":
                        raise

    db.table("payments").update({
        "status": "approved",
        "razorpay_payment_id": rzp_pay,
        "razorpay_signature": rzp_sig,
    }).eq("id", payment_id).execute()

    coupon_id = payment_row.get("coupon_id")
    if coupon_id:
        coupon_row = db.table("coupons").select("*").eq("id", coupon_id).single().execute()
        if coupon_row.data:
            _record_coupon_usage(
                db, coupon_row.data, user_id, payment_id,
                float(payment_row.get("discount_amount") or 0),
                payment_row.get("affiliate_id"),
                float(payment_row.get("commission_amount") or 0),
            )

    try:
        profile = db.table("profiles").select("email").eq("id", user_id).single().execute()
        to_email = profile.data.get("email") if profile.data else None
        if to_email:
            await send_email(
                to_email=to_email,
                subject="Payment confirmed — Caliber Education",
                html_content=(
                    "<p>Hi,</p><p>Your Scholarship Test registration is confirmed. You can take the "
                    "test from the MCQ page.</p><p>All the best!</p>"
                    if scholarship.ACCESS_PREFIX in (payment_row.get("utr_number") or "") else
                    "<p>Hi,</p><p>Your MCQ test series payment has been verified and your selected "
                    "subjects are now unlocked.</p><p>Log in to your dashboard to get started.</p>"
                ),
            )
    except Exception as e:
        print(f"[EMAIL] Failed to send MCQ purchase confirmation for user {user_id}: {e}")

    return {
        "success": True,
        "message": "MCQ package activated successfully! All selected test series are now unlocked.",
    }


# ─── Test Series Payment Endpoints ───────────────────────────────────────────
# Same shape as the MCQ package endpoints above, minus the duration dimension
# (test series is a one-time purchase, not a subscription).

@router.post("/create-test-series-order", status_code=201)
@limiter.limit("10/minute")
async def create_test_series_order(
    request: Request,
    body: CreateTestSeriesOrderRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    settings = get_settings()
    if not body.subjectIds:
        raise HTTPException(status_code=400, detail="No subjects selected")

    calc = calculate_test_series_cart(body.level, body.subjectIds, db)
    if not calc.get("purchasable", True):
        raise HTTPException(
            status_code=400,
            detail="Some of these papers aren't sold individually — select a full Group or add the rest of that group's papers.",
        )
    base_price = calc["real_total_price"]
    discounted_price = calc["discounted_price"]

    coupon, coupon_discount, affiliate_id, commission_amount = _resolve_coupon(
        db, body.couponCode, f"testseries-{body.level.lower()}", current_user["id"], discounted_price
    )
    final_price = max(0.0, discounted_price - coupon_discount)
    amount_paise = int(final_price * 100)

    rzp = _get_razorpay_client()
    if rzp:
        try:
            order = rzp.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": f"ts_{body.level[:5].lower()}",
                "notes": {
                    "type": "test_series",
                    "level": body.level,
                    "subject_ids": ",".join(body.subjectIds),
                    "user_id": current_user["id"],
                    "bundle_id": calc.get("applied_bundle_id") or "",
                },
            })
            order_id = order["id"]
        except Exception as e:
            print(f"Razorpay API Error during test series order, falling back to dummy ID: {e}")
            order_id = f"order_TS_FALLBACK_{uuid.uuid4().hex[:8].upper()}"
    else:
        order_id = f"order_TS_{uuid.uuid4().hex[:12].upper()}"

    try:
        db.table("payments").insert({
            "user_id": current_user["id"],
            "course_id": None,
            "utr_number": f"testseries-{body.level.lower()}|" + ",".join(body.subjectIds) + f"|{uuid.uuid4().hex[:8]}",
            "amount": final_price,
            "original_amount": base_price,
            "discount_amount": base_price - final_price,
            "coupon_id": coupon["id"] if coupon else None,
            "affiliate_id": affiliate_id,
            "commission_amount": commission_amount,
            "status": "pending",
            "razorpay_order_id": order_id,
        }).execute()
    except Exception as e:
        print("Error inserting test series payment:", e)

    return {
        "orderId": order_id,
        "amount": amount_paise,
        "currency": "INR",
        "key": settings.razorpay_key_id or "rzp_test_demo",
        "originalAmount": int(base_price * 100),
        "discountAmount": int((base_price - final_price) * 100),
        "finalAmount": int(final_price * 100),
        "savingsAmount": calc["savings_amount"],
        "appliedBundle": calc.get("applied_bundle_title"),
        "couponCode": coupon["code"] if coupon else None,
    }


@router.post("/mock-confirm-test-series")
async def mock_confirm_test_series(
    body: VerifyPaymentRequest,
    current_user: dict = Depends(require_admin),
    db: Client = Depends(get_db),
):
    if os.getenv("ALLOW_TEST_PAYMENTS", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Test payments are currently disabled.")
    return await _apply_test_series_grant(db, body.razorpay_order_id, current_user["id"], "pay_TEST_TS", "mock_signature")


@router.post("/verify-test-series-payment")
@limiter.limit("20/minute")
async def verify_test_series_payment(
    request: Request,
    body: VerifyPaymentRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    settings = get_settings()
    if not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Payment verification is not configured. Please contact support.")
    rzp = _get_razorpay_client()
    try:
        params_dict = {
            'razorpay_order_id': body.razorpay_order_id,
            'razorpay_payment_id': body.razorpay_payment_id,
            'razorpay_signature': body.razorpay_signature
        }
        rzp.utility.verify_payment_signature(params_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    result = await _apply_test_series_grant(db, body.razorpay_order_id, current_user["id"], body.razorpay_payment_id, body.razorpay_signature)
    # See verify-mcq-payment's comment above — the frontend only checks the
    # HTTP status, so a grant failure must not come back as a 200.
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Payment record not found"))
    return result


async def _apply_test_series_grant(db: Client, order_id: str, user_id: str, rzp_pay: str, rzp_sig: str):
    # Scoped to the caller — see _apply_mcq_grant's comment above; same
    # ownership gap fixed here.
    payment = db.table("payments").select("*").eq("razorpay_order_id", order_id).eq("user_id", user_id).execute()
    if not payment.data:
        return {"success": False, "message": "No matching payment found"}

    payment_row = payment.data[0]
    payment_id = payment_row["id"]

    # Idempotency guard: a replayed/retried verify call for a payment
    # already marked approved must not re-run the grant a second time —
    # mirrors the check the webhook handler already applies before
    # dispatching.
    if payment_row.get("status") == "approved":
        return {"success": True, "message": "Test series access already activated."}

    # Grant the actual test-series enrollments BEFORE marking the payment
    # approved — no try/except swallowing on purpose, same reasoning as
    # _apply_mcq_grant: a failure must propagate so the payment stays
    # "pending" and can be retried, instead of silently looking approved
    # with nothing delivered.
    packed = payment_row.get("utr_number", "")
    if packed.startswith("testseries-") and "|" in packed:
        subjects_list = packed.split("|", 2)[1].split(",")
        for sub_id in subjects_list:
            sub_id = sub_id.strip()
            if not sub_id:
                continue
            existing = (
                db.table("test_series_enrollments")
                .select("id")
                .eq("user_id", user_id)
                .eq("subject_id", sub_id)
                .execute()
            )
            if existing.data:
                db.table("test_series_enrollments").update({
                    "payment_id": payment_id,
                }).eq("id", existing.data[0]["id"]).execute()
            else:
                try:
                    db.table("test_series_enrollments").insert({
                        "user_id": user_id,
                        "subject_id": sub_id,
                        "payment_id": payment_id,
                        "access_until": None,  # lifetime — one-time purchase
                    }).execute()
                except PostgrestAPIError as e:
                    # See the matching comment in _apply_mcq_grant — a
                    # concurrent request already granted this exact
                    # (user_id, subject_id) enrollment; benign no-op.
                    if e.code != "23505":
                        raise

    db.table("payments").update({
        "status": "approved",
        "razorpay_payment_id": rzp_pay,
        "razorpay_signature": rzp_sig,
    }).eq("id", payment_id).execute()

    coupon_id = payment_row.get("coupon_id")
    if coupon_id:
        coupon_row = db.table("coupons").select("*").eq("id", coupon_id).single().execute()
        if coupon_row.data:
            _record_coupon_usage(
                db, coupon_row.data, user_id, payment_id,
                float(payment_row.get("discount_amount") or 0),
                payment_row.get("affiliate_id"),
                float(payment_row.get("commission_amount") or 0),
            )

    try:
        profile = db.table("profiles").select("email").eq("id", user_id).single().execute()
        to_email = profile.data.get("email") if profile.data else None
        if to_email:
            await send_email(
                to_email=to_email,
                subject="Payment confirmed — Caliber Education",
                html_content=(
                    "<p>Hi,</p><p>Your test series payment has been verified and your purchased "
                    "subjects are now unlocked.</p><p>Log in to your dashboard to get started.</p>"
                ),
            )
    except Exception as e:
        print(f"[EMAIL] Failed to send test series purchase confirmation for user {user_id}: {e}")

    return {
        "success": True,
        "message": "Test series activated! Your purchased subjects are now unlocked.",
    }


# ─── Manual UPI Payment Path (Razorpay not live yet) ────────────────────────
# Student pays via a static UPI QR code shown in the frontend, then submits
# their UPI transaction reference here instead of going through Razorpay
# checkout. Creates a "pending" row exactly like the Razorpay create-*-order
# endpoints do, using a synthetic razorpay_order_id so the SAME grant
# functions (_apply_course_grant_or_extend, _apply_mcq_grant,
# _apply_test_series_grant) work completely unchanged once an admin approves
# it — see admin.py's approve_payment. The Razorpay path above is untouched;
# these are new, additive endpoints only.

class SubmitManualCourseRequest(CreateOrderRequest):
    upiReference: str
    payerUpiId: str
    payerName: str


class SubmitManualMCQRequest(CreateMCQOrderRequest):
    upiReference: str
    payerUpiId: str
    payerName: str


class SubmitManualScholarshipRequest(CreateScholarshipOrderRequest):
    upiReference: str
    payerUpiId: str
    payerName: str


class SubmitManualTestSeriesRequest(CreateTestSeriesOrderRequest):
    upiReference: str
    payerUpiId: str
    payerName: str


def _insert_manual_payment(db: Client, payment_row: dict, upi_reference: str, payer_upi_id: str, payer_name: str) -> dict:
    """Shared insert path for all three submit-manual-* endpoints below.
    Normalizes the reference, rejects an already-used one (app-level check,
    with the DB's partial unique index as the race-safe backstop for two
    simultaneous submissions of the same reference). Also records who the
    student says they paid from (their own UPI ID + name) — not verified
    against anything, just carried through so admin has enough to cross-check
    against their actual bank/UPI app transaction list."""
    reference = upi_reference.strip()
    if not reference:
        raise HTTPException(status_code=400, detail="Please enter your UPI transaction reference.")
    payer_upi_id = payer_upi_id.strip()
    payer_name = payer_name.strip()
    if not payer_upi_id or not payer_name:
        raise HTTPException(status_code=400, detail="Please enter the UPI ID and name you paid from.")

    existing = (
        db.table("payments").select("id")
        .eq("payment_reference", reference)
        .eq("payment_method", "manual_upi")
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=400,
            detail="This payment reference has already been submitted. Contact support if this is an error.",
        )

    payment_row["payment_method"] = "manual_upi"
    payment_row["payment_reference"] = reference
    payment_row["payer_upi_id"] = payer_upi_id
    payment_row["payer_name"] = payer_name
    try:
        result = db.table("payments").insert(payment_row).execute()
    except PostgrestAPIError as e:
        if e.code == "23505":
            raise HTTPException(
                status_code=400,
                detail="This payment reference has already been submitted. Contact support if this is an error.",
            )
        raise
    return result.data[0] if result.data else {}


@router.post("/submit-manual-course", status_code=201)
@limiter.limit("10/minute")
async def submit_manual_course(
    request: Request,
    body: SubmitManualCourseRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Manual-UPI equivalent of create_order — identical item resolution and
    coupon logic, no Razorpay call, creates a pending row for admin review."""
    bundle = None
    if body.courseId:
        try:
            uuid.UUID(body.courseId)
            bundle = db.table("course_bundles").select("id, title, price, course_ids").eq("id", body.courseId).execute()
        except ValueError:
            bundle = None

    is_multi_course_cart = False
    original_price = 0.0

    if bundle and bundle.data:
        price = float(bundle.data[0].get("price") or 0)
        original_price = price
        active_course_id = body.courseId
    elif body.courseIds and len(body.courseIds) > 0:
        is_multi_course_cart = True
        courses_res = db.table("courses").select("id, title, price").in_("id", body.courseIds).execute()
        if not courses_res.data:
            raise HTTPException(status_code=404, detail="Items not found in database")
        price = sum(float(c.get("price") or 0) for c in courses_res.data)
        original_price = price
        active_course_id = ",".join(body.courseIds)
    else:
        course = db.table("courses").select("id, title, price").eq("id", body.courseId).single().execute()
        if not course.data:
            raise HTTPException(status_code=404, detail="Item not found")
        price = float(course.data.get("price") or 0)
        original_price = price
        active_course_id = body.courseId

    coupon, discount_amount, affiliate_id, commission_amount = _resolve_coupon(
        db, body.couponCode, active_course_id, current_user["id"], price
    )
    final_price = max(0, price - discount_amount)

    payment_row = {
        "user_id": current_user["id"],
        "course_id": None if is_multi_course_cart else active_course_id,
        "amount": final_price,
        "original_amount": original_price,
        "discount_amount": discount_amount,
        "coupon_id": coupon["id"] if coupon else None,
        "affiliate_id": affiliate_id,
        "commission_amount": commission_amount,
        "status": "pending",
        "razorpay_order_id": f"manual_{uuid.uuid4().hex}",
    }
    if is_multi_course_cart:
        payment_row["utr_number"] = "courses|" + ",".join(body.courseIds) + f"|{uuid.uuid4().hex[:8]}"

    _insert_manual_payment(db, payment_row, body.upiReference, body.payerUpiId, body.payerName)

    return {
        "success": True,
        "amount": final_price,
        "originalAmount": original_price,
        "discountAmount": discount_amount,
        "couponCode": coupon["code"] if coupon else None,
        "message": "Payment submitted for verification. You'll get access once our team confirms it.",
    }


@router.post("/submit-manual-mcq", status_code=201)
@limiter.limit("10/minute")
async def submit_manual_mcq(
    request: Request,
    body: SubmitManualMCQRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Manual-UPI equivalent of create_mcq_order."""
    if not body.subjectIds:
        raise HTTPException(status_code=400, detail="No subjects selected")

    calc = calculate_mcq_cart(body.level, body.subjectIds, body.duration, db)
    base_price = calc["real_total_price"]
    discounted_price = calc["discounted_price"]

    coupon, coupon_discount, affiliate_id, commission_amount = _resolve_coupon(
        db, body.couponCode, f"mcq-{body.level.lower()}", current_user["id"], discounted_price
    )
    final_price = max(0.0, discounted_price - coupon_discount)

    payment_row = {
        "user_id": current_user["id"],
        "course_id": None,
        "utr_number": f"mcq-{body.level.lower()}-{body.duration}|" + ",".join(body.subjectIds) + f"|{uuid.uuid4().hex[:8]}",
        "amount": final_price,
        "original_amount": base_price,
        "discount_amount": base_price - final_price,
        "coupon_id": coupon["id"] if coupon else None,
        "affiliate_id": affiliate_id,
        "commission_amount": commission_amount,
        "status": "pending",
        "razorpay_order_id": f"manual_{uuid.uuid4().hex}",
    }

    _insert_manual_payment(db, payment_row, body.upiReference, body.payerUpiId, body.payerName)

    return {
        "success": True,
        "amount": final_price,
        "originalAmount": base_price,
        "discountAmount": base_price - final_price,
        "savingsAmount": calc["savings_amount"],
        "appliedBundle": calc.get("applied_bundle_title"),
        "couponCode": coupon["code"] if coupon else None,
        "message": "Payment submitted for verification. You'll get access once our team confirms it.",
    }


@router.post("/submit-manual-scholarship", status_code=201)
@limiter.limit("10/minute")
async def submit_manual_scholarship(
    request: Request,
    body: SubmitManualScholarshipRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Manual-UPI equivalent of create_scholarship_order; access comes when an
    admin approves the payment (Admin → Payments), like other MCQ purchases."""
    co = _scholarship_checkout(db, body.paperId, current_user["id"], body.couponCode)
    row = {**co["row"], "razorpay_order_id": f"manual_{uuid.uuid4().hex}"}
    _insert_manual_payment(db, row, body.upiReference, body.payerUpiId, body.payerName)
    return {
        "success": True,
        "amount": co["final_price"],
        "message": "Payment submitted for verification. You'll be able to take the test once our team confirms it.",
    }


@router.post("/submit-manual-test-series", status_code=201)
@limiter.limit("10/minute")
async def submit_manual_test_series(
    request: Request,
    body: SubmitManualTestSeriesRequest,
    current_user: dict = Depends(get_current_user),
    db: Client = Depends(get_db),
):
    """Manual-UPI equivalent of create_test_series_order."""
    if not body.subjectIds:
        raise HTTPException(status_code=400, detail="No subjects selected")

    calc = calculate_test_series_cart(body.level, body.subjectIds, db)
    if not calc.get("purchasable", True):
        raise HTTPException(
            status_code=400,
            detail="Some of these papers aren't sold individually — select a full Group or add the rest of that group's papers.",
        )
    base_price = calc["real_total_price"]
    discounted_price = calc["discounted_price"]

    coupon, coupon_discount, affiliate_id, commission_amount = _resolve_coupon(
        db, body.couponCode, f"testseries-{body.level.lower()}", current_user["id"], discounted_price
    )
    final_price = max(0.0, discounted_price - coupon_discount)

    payment_row = {
        "user_id": current_user["id"],
        "course_id": None,
        "utr_number": f"testseries-{body.level.lower()}|" + ",".join(body.subjectIds) + f"|{uuid.uuid4().hex[:8]}",
        "amount": final_price,
        "original_amount": base_price,
        "discount_amount": base_price - final_price,
        "coupon_id": coupon["id"] if coupon else None,
        "affiliate_id": affiliate_id,
        "commission_amount": commission_amount,
        "status": "pending",
        "razorpay_order_id": f"manual_{uuid.uuid4().hex}",
    }

    _insert_manual_payment(db, payment_row, body.upiReference, body.payerUpiId, body.payerName)

    return {
        "success": True,
        "amount": final_price,
        "originalAmount": base_price,
        "discountAmount": base_price - final_price,
        "savingsAmount": calc["savings_amount"],
        "appliedBundle": calc.get("applied_bundle_title"),
        "couponCode": coupon["code"] if coupon else None,
        "message": "Payment submitted for verification. You'll get access once our team confirms it.",
    }


# ─── Razorpay Webhook (authoritative confirmation path) ─────────────────────
# Configure this URL + a webhook secret in the Razorpay dashboard (Settings ->
# Webhooks), subscribed to "payment.captured". This is the source of truth
# for entitlement grants independent of whether the client's browser stayed
# open long enough to call /verify-payment itself.

@router.post("/webhook")
@limiter.limit("60/minute")
async def razorpay_webhook(request: Request, db: Client = Depends(get_db)):
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    body_bytes = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = json.loads(body_bytes)
    if payload.get("event") != "payment.captured":
        return {"success": True, "ignored": payload.get("event")}

    entity = payload["payload"]["payment"]["entity"]
    order_id = entity.get("order_id")
    rzp_payment_id = entity.get("id")

    payment = db.table("payments").select("*").eq("razorpay_order_id", order_id).execute()
    if not payment.data:
        return {"success": True, "note": "no matching payment row for this order"}
    payment_row = payment.data[0]

    if payment_row.get("status") == "approved":
        return {"success": True, "note": "already processed"}  # idempotent — safe to retry/redeliver

    utr = payment_row.get("utr_number") or ""
    is_mcq = payment_row.get("course_id") is None and utr.startswith("mcq-")
    is_test_series = payment_row.get("course_id") is None and utr.startswith("testseries-")
    if is_mcq:
        await _apply_mcq_grant(db, order_id, payment_row["user_id"], rzp_payment_id, "webhook_verified")
    elif is_test_series:
        await _apply_test_series_grant(db, order_id, payment_row["user_id"], rzp_payment_id, "webhook_verified")
    else:
        settings = get_settings()
        user_res = db.table("profiles").select("email").eq("id", payment_row["user_id"]).single().execute()
        email = user_res.data.get("email") if user_res.data else None
        await _apply_course_grant_or_extend(db, payment_row, payment_row["user_id"], email, rzp_payment_id, "webhook_verified", settings)

    return {"success": True}
