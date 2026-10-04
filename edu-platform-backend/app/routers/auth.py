import asyncio
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from gotrue.errors import AuthApiError
from supabase import Client

from app.core.config import get_settings
from app.core.database import get_db, get_auth_client
from app.core.limiter import limiter
from app.core.security import create_access_token
from app.dependencies import get_current_user
from pydantic import BaseModel
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterInitRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    VerifyOTPRequest,
)

class GoogleExchangeRequest(BaseModel):
    access_token: str

router = APIRouter(prefix="/api/auth", tags=["Auth"])


async def _verify_turnstile(token: str) -> bool:
    """Validates Cloudflare Turnstile token. Only skipped in local development."""
    settings = get_settings()
    if settings.app_env == "development":
        return True  # Skip validation only in local development
    if not settings.turnstile_secret_key:
        # Fail closed outside dev: never silently skip bot-checking because
        # a secret happened to be unset on the deployed environment.
        return False
    async with httpx.AsyncClient() as client:
        res = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": settings.turnstile_secret_key, "response": token},
        )
        data = res.json()
        return data.get("success", False)


@router.post("/register-init")
@limiter.limit("5/minute")
async def register_init(request: Request, body: RegisterInitRequest, db: Client = Depends(get_db)):
    """Step 1: Request OTP for email registration.

    Uses Supabase Auth's own OTP email (no third-party sender). For this to
    deliver a 6-digit code rather than a magic link, the Supabase dashboard's
    "Magic Link" email template must include {{ .Token }} — see SETUP_GUIDE.
    """
    if not await _verify_turnstile(body.turnstileToken):
        raise HTTPException(status_code=400, detail="Bot verification failed")

    # Normalize so a mixed-case typed email always matches the lowercase
    # address Supabase stores on the auth user / profiles row.
    body.email = body.email.strip().lower()

    # Don't let a FULLY registered account silently restart the signup flow —
    # send them to sign-in instead of emailing a code that would look like a
    # second registration. `active_session_id` is only ever set once step 3
    # (password set) or a real login succeeds, so a profile row that exists
    # but has no active_session_id is a signup that got interrupted before a
    # password was ever set — that email must be allowed to retry, or it
    # would be locked out forever (can't register: already exists; can't log
    # in: no password).
    existing = db.table("profiles").select("id, active_session_id").eq("email", body.email).execute()
    if existing.data and existing.data[0].get("active_session_id"):
        raise HTTPException(
            status_code=409,
            detail="This email is already registered. Please sign in instead.",
        )

    try:
        get_auth_client().auth.sign_in_with_otp({
            "email": body.email,
            "options": {"should_create_user": True},
        })
    except AuthApiError as e:
        print(f"[AUTH] Supabase OTP send failed for {body.email}: {e}")
        # Supabase's own shared email sender caps all auth emails at a
        # project-wide per-hour limit (Authentication -> Rate Limits in the
        # dashboard) unless custom SMTP is configured. Surfacing this
        # distinctly from other failures means "wait a bit" doesn't get
        # misread as "something is broken".
        if e.code == "over_email_send_rate_limit" or e.status == 429:
            raise HTTPException(status_code=429, detail="We've hit Supabase's email sending limit for now. Please wait a few minutes and try again.")
        raise HTTPException(status_code=502, detail="Couldn't send the verification code. Please try again in a moment.")
    except Exception as e:
        print(f"[AUTH] Supabase OTP send failed for {body.email}: {e}")
        raise HTTPException(status_code=502, detail="Couldn't send the verification code. Please try again in a moment.")

    print(f"[AUTH] Supabase OTP requested for {body.email}")
    return {"success": True, "message": "OTP sent successfully"}


@router.post("/verify-otp")
@limiter.limit("10/minute")
async def verify_otp(request: Request, body: VerifyOTPRequest, db: Client = Depends(get_db)):
    """Step 2: Verify the Supabase-issued OTP, then hand back a short-lived
    temp token that authorizes step 3 (setting a password)."""
    body.email = body.email.strip().lower()
    try:
        res = get_auth_client().auth.verify_otp({
            "email": body.email,
            "token": body.otp,
            "type": "email",
        })
    except Exception as e:
        print(f"[AUTH] OTP verify failed for {body.email}: {e}")
        raise HTTPException(status_code=401, detail="Incorrect or expired code. Request a new one.")

    if not res or not res.user:
        raise HTTPException(status_code=401, detail="Incorrect or expired code. Request a new one.")

    from jose import jwt as _jwt
    import time
    settings = get_settings()
    temp_token = _jwt.encode(
        {"sub": f"otp:{body.email}", "purpose": "registration", "exp": time.time() + 900},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return {"success": True, "tempToken": temp_token}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterRequest, db: Client = Depends(get_db)):
    """Step 3: Create account with validated email + password."""
    settings = get_settings()
    body.email = body.email.strip().lower()
    # Validate temp token
    from jose import jwt as _jwt, JWTError
    try:
        payload = _jwt.decode(body.tempToken, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        sub: str = payload.get("sub", "")
        purpose = payload.get("purpose", "")
        if not sub.startswith("otp:") or purpose != "registration":
            raise ValueError
        email_from_token = sub.replace("otp:", "")
        if email_from_token.lower() != body.email.lower():
            raise ValueError
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired temp token")

    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if len(body.password) > 128:
        raise HTTPException(status_code=400, detail="Password must be under 128 characters")

    # The frontend gate on this is client-side only and trivially bypassed by
    # calling this endpoint directly — this is the real enforcement, at the
    # point the profiles row (the actual account) gets created below.
    if not body.termsAccepted:
        raise HTTPException(status_code=400, detail="You must accept the Terms & Conditions to create an account.")

    # The Supabase user already exists at this point — sign_in_with_otp in
    # step 1 created it (should_create_user) and step 2's verify_otp confirmed
    # the address. So this sets the password on that existing user rather than
    # calling sign_up (which would fail as "already registered").
    profile_lookup = db.table("profiles").select("id").eq("email", body.email).execute()
    if not profile_lookup.data:
        # The tempToken decoded fine, so email verification did happen — this
        # means the registration attempt it belongs to no longer exists
        # (e.g. superseded by a later retry). Not a "you skipped a step"
        # case, just a stale session.
        raise HTTPException(status_code=400, detail="Your signup session has expired. Please start again from the beginning.")
    user_id = str(profile_lookup.data[0]["id"])

    try:
        db.auth.admin.update_user_by_id(user_id, {"password": body.password})
    except Exception as e:
        print(f"[AUTH] Failed to set password for {body.email}: {e}")
        raise HTTPException(status_code=500, detail="Couldn't set your password. Please try again.")

    session_id = str(uuid.uuid4())
    db.table("profiles").upsert({
        "id": user_id,
        "email": body.email,
        "role": "student",
        "active_session_id": session_id
    }).execute()

    token = create_access_token({"sub": user_id, "email": body.email, "role": "student", "session_id": session_id})
    return TokenResponse(
        token=token,
        user=UserResponse(id=user_id, email=body.email, role="student", profileComplete=False),
    )


def _is_profile_complete(profile: dict) -> bool:
    return bool(profile.get("full_name")) and bool(profile.get("phone_number"))


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: Client = Depends(get_db)):
    """Login with email and password."""
    if not await _verify_turnstile(body.turnstileToken):
        raise HTTPException(status_code=400, detail="Bot verification failed")

    body.email = body.email.strip().lower()
    try:
        auth_res = get_auth_client().auth.sign_in_with_password({"email": body.email, "password": body.password})
    except Exception:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if not auth_res.user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    user_id = str(auth_res.user.id)

    # Fetch profile for role
    profile = db.table("profiles").select("*").eq("id", user_id).single().execute()
    role = profile.data.get("role", "student") if profile.data else "student"
    complete = _is_profile_complete(profile.data) if profile.data else False

    session_id = str(uuid.uuid4())
    db.table("profiles").update({"active_session_id": session_id}).eq("id", user_id).execute()

    token = create_access_token({"sub": user_id, "email": body.email, "role": role, "session_id": session_id})
    return TokenResponse(
        token=token,
        user=UserResponse(id=user_id, email=body.email, role=role, profileComplete=complete),
    )


@router.get("/google/url")
@limiter.limit("20/minute")
async def get_google_auth_url(request: Request):
    """Return the Supabase Google OAuth authorize URL."""
    settings = get_settings()
    # E.g., http://localhost:3000/auth/callback
    redirect_to = f"{settings.frontend_url}/auth/callback"
    # Construct manually or via library (constructing manually is more robust here)
    supabase_url = settings.supabase_url
    url = f"{supabase_url}/auth/v1/authorize?provider=google&redirect_to={redirect_to}"
    return {"url": url}


@router.post("/google/exchange", response_model=TokenResponse)
@limiter.limit("10/minute")
async def google_exchange(request: Request, body: GoogleExchangeRequest, db: Client = Depends(get_db)):
    """Exchange Supabase token for our custom JWT."""
    try:
        # Validate the token directly via Supabase Auth
        res = db.auth.get_user(body.access_token)
    except Exception as e:
        print(f"Supabase Auth error: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google token")

    if not res.user:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    user_id = str(res.user.id)
    email = res.user.email

    try:
        # Try to fetch existing profile without .single() to avoid exception on 0 rows
        profile_res = db.table("profiles").select("*").eq("id", user_id).execute()
        role = "student"
        complete = False
        session_id = str(uuid.uuid4())

        if profile_res.data:
            role = profile_res.data[0].get("role", "student")
            complete = _is_profile_complete(profile_res.data[0])
            db.table("profiles").update({"active_session_id": session_id}).eq("id", user_id).execute()
        else:
            # Create profile safely if it doesn't exist — Google gives us no
            # phone/address, so this is never complete on first sign-in
            db.table("profiles").upsert({"id": user_id, "email": email, "role": "student", "active_session_id": session_id}).execute()
    except Exception as e:
        print(f"Database error during profile fetch/create: {e}")
        role = "student"
        complete = False
        session_id = str(uuid.uuid4())

    # Generate custom caliber jwt
    token = create_access_token({"sub": user_id, "email": email, "role": role, "session_id": session_id})

    return TokenResponse(
        token=token,
        user=UserResponse(id=user_id, email=email, role=role, profileComplete=complete),
    )


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user), db: Client = Depends(get_db)):
    """Return current user profile with enrolled courses and recent quiz attempts."""
    user_id = current_user["id"]

    def fetch_enrollments():
        return db.table("enrollments").select("course_id, purchased_at, access_until").eq("user_id", user_id).execute()

    def fetch_attempts():
        return (
            db.table("quiz_attempts")
            .select("set_id, score, total, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )

    def fetch_profile():
        try:
            return db.table("profiles").select("full_name, phone_number, address, stage, attempt_status").eq("id", user_id).single().execute()
        except Exception:
            return None

    def fetch_mcq_enrollments():
        return db.table("mcq_enrollments").select("subject_code, access_until").eq("user_id", user_id).execute()

    # These 4 queries are independent of each other — run them concurrently
    # via threads instead of stacking 4 sequential Supabase round trips
    # (supabase-py's client is sync/blocking, hence asyncio.to_thread rather
    # than a native async client call).
    enrollments, attempts, profile, mcq_enrollments = await asyncio.gather(
        asyncio.to_thread(fetch_enrollments),
        asyncio.to_thread(fetch_attempts),
        asyncio.to_thread(fetch_profile),
        asyncio.to_thread(fetch_mcq_enrollments),
    )

    enrolled_ids = [e["course_id"] for e in (enrollments.data or [])]
    enrolled_data = enrollments.data or []

    attempts_data = attempts.data or []
    attempt_set_ids = list({a["set_id"] for a in attempts_data if a.get("set_id")})
    paper_titles = {}
    scholarship_ids = set()
    if attempt_set_ids:
        try:
            # "*" rather than naming is_scholarship, so this still works
            # before scholarship_test_migration.sql has been run.
            papers = db.table("mcq_papers").select("*").in_("id", attempt_set_ids).execute()
            paper_titles = {p["id"]: p["title"] for p in (papers.data or [])}
            scholarship_ids = {p["id"] for p in (papers.data or []) if p.get("is_scholarship")}
        except Exception:
            pass
    # Scholarship marks stay hidden until results are published, and even
    # then they're shown on their own result page — never in this list.
    attempts_data = [a for a in attempts_data if a.get("set_id") not in scholarship_ids]
    for a in attempts_data:
        a["paperTitle"] = paper_titles.get(a.get("set_id"), "MCQ Paper")

    profile_data = profile.data if (profile is not None and profile.data) else {}

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # Deduplicate — keep only the latest active enrollment per subject_code
    best_expiry = {}  # subject_code -> latest access_until datetime
    for e in (mcq_enrollments.data or []):
        code = e["subject_code"]
        expiry_str = e.get("access_until")
        if expiry_str:
            try:
                expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00").replace(" ", "T"))
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                if expiry_dt <= now:
                    continue  # expired
                if code not in best_expiry or expiry_dt > best_expiry[code]:
                    best_expiry[code] = expiry_dt
            except ValueError:
                # If can't parse, include it
                if code not in best_expiry:
                    best_expiry[code] = now
        else:
            # No expiry = lifetime access
            if code not in best_expiry:
                best_expiry[code] = now

    mcq_enrolled_ids = list(best_expiry.keys())

    return {
        "user": {**current_user, **profile_data},
        "purchases": enrolled_ids,
        "enrollments_data": enrolled_data,
        "mcqPurchases": mcq_enrolled_ids,
        "attempts": attempts_data,
    }

class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    phone_number: str | None = None
    address: str | None = None
    stage: str | None = None
    attempt_status: str | None = None

@router.put("/profile")
async def update_profile(body: ProfileUpdateRequest, current_user: dict = Depends(get_current_user), db: Client = Depends(get_db)):
    """Update user's extended profile details."""
    user_id = current_user["id"]
    update_data = {}
    if body.full_name is not None: update_data["full_name"] = body.full_name.strip()
    if body.phone_number is not None:
        phone = body.phone_number.strip()
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) < 7 or len(digits) > 15:
            raise HTTPException(status_code=400, detail="Enter a valid phone number.")
        update_data["phone_number"] = phone
    if body.address is not None:
        address = body.address.strip()
        if len(address) > 500:
            raise HTTPException(status_code=400, detail="Address is too long.")
        update_data["address"] = address
    if body.stage is not None: update_data["stage"] = body.stage
    if body.attempt_status is not None: update_data["attempt_status"] = body.attempt_status

    if not update_data:
        return {"success": True}

    try:
        db.table("profiles").update(update_data).eq("id", user_id).execute()
    except Exception as e:
        print(f"Profile update error: {e}")
        raise HTTPException(status_code=500, detail="Could not update profile information")

    # Returned so the frontend can sync its form from confirmed server state
    # (e.g. the trimming above) instead of trusting its own optimistic values.
    return {"success": True, "message": "Profile updated successfully", "profile": update_data}


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    if not await _verify_turnstile(body.turnstileToken):
        raise HTTPException(status_code=400, detail="Bot verification failed")
    body.email = body.email.strip().lower()
    settings = get_settings()
    try:
        get_auth_client().auth.reset_password_email(
            body.email,
            {"redirect_to": f"{settings.frontend_url}/reset-password"},
        )
    except Exception as e:
        print(f"[AUTH] Password reset email failed for {body.email}: {e}")
        pass  # Always respond 200 to prevent user enumeration
    return {"success": True, "message": "If this email exists, a reset link has been sent"}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, body: ResetPasswordRequest):
    """Step 2 of the forgot-password flow: the recovery link Supabase emailed
    redirects here with an access/refresh token pair identifying exactly
    which user is resetting. A fresh, single-use client establishes that
    specific session via set_session before changing the password — using
    the shared get_db() client here would apply the change to whichever
    session it happened to be holding at that moment, not necessarily this
    user."""
    if len(body.newPassword) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if len(body.newPassword) > 128:
        raise HTTPException(status_code=400, detail="Password must be under 128 characters")
    client = get_auth_client()
    try:
        client.auth.set_session(body.accessToken, body.refreshToken)
        client.auth.update_user({"password": body.newPassword})
    except Exception as e:
        print(f"[AUTH] Password reset failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid or expired reset link. Please request a new one.")
    return {"success": True, "message": "Password updated successfully"}


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user), db: Client = Depends(get_db)):
    """Invalidates the caller's current JWT server-side by rotating
    profiles.active_session_id to a fresh value — the single-active-session
    check in get_current_user() then rejects this token on its next use,
    since its embedded session_id claim can never match again. Previously
    there was no backend logout at all: the frontend only cleared
    localStorage, so a "logged out" JWT stayed valid (matched
    active_session_id) until it naturally expired or another login
    overwrote the session elsewhere."""
    db.table("profiles").update({"active_session_id": str(uuid.uuid4())}).eq("id", current_user["id"]).execute()
    return {"success": True}
