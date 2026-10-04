import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError as PostgrestAPIError
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.limiter import limiter
from app.routers import auth, courses, payments, mcq, sessions, tests, contact, admin, test_series
from app.routers.coupons import router as coupons_router, admin_router as coupons_admin_router
from app.routers.free_resources import router as free_resources_router, admin_router as free_resources_admin_router
from app.routers.mcq_import import router as mcq_import_router

settings = get_settings()

# Non-fatal go-live guardrails: a misconfigured production deploy should be
# loud in the logs, not silently take real signups with test-mode payment
# settings. Deliberately doesn't raise — a startup crash from this check
# would be worse than a misconfigured-but-running server.
if settings.app_env == "production":
    if settings.razorpay_key_id.startswith("rzp_test_"):
        print("[STARTUP WARNING] APP_ENV=production but RAZORPAY_KEY_ID is a TEST key (rzp_test_...). Real payments will fail until this is switched to a rzp_live_ key.")
    if os.getenv("ALLOW_TEST_PAYMENTS", "false").lower() == "true":
        print("[STARTUP WARNING] APP_ENV=production but ALLOW_TEST_PAYMENTS=true — the mock-confirm test-payment bypass is live. Set ALLOW_TEST_PAYMENTS=false for production.")
    if not os.getenv("RAZORPAY_WEBHOOK_SECRET"):
        print("[STARTUP WARNING] RAZORPAY_WEBHOOK_SECRET is not set — the /api/payments/webhook endpoint will reject all webhook deliveries (503) until this is configured in both Razorpay's dashboard and this server's env.")

# Public API docs make sense during development but are a free recon aid in
# production — every route, request/response schema, and parameter name
# (including admin/payment-adjacent ones) enumerable with no auth. Disabled
# outside dev; set APP_ENV=development locally if you want /docs back.
app = FastAPI(
    title="Caliber Education API",
    description="Backend API for the Caliber Education platform — CA prep courses, MCQ practice, 1:1 mentoring, and test evaluations.",
    version="1.0.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
)

# ─── Rate limiting (per client IP) ───────────────────────────────────────────
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # slowapi's default handler returns {"error": ...} — every other error in
    # this API returns {"detail": ...} (FastAPI's own convention), and every
    # frontend catch block only ever reads err.detail. Keeping this
    # consistent means rate-limit errors show a real message instead of
    # silently falling back to a generic "something went wrong".
    return JSONResponse(
        status_code=429,
        content={"detail": f"Too many attempts. Please wait a moment and try again ({exc.detail})."},
    )


@app.exception_handler(PostgrestAPIError)
async def postgrest_error_handler(request: Request, exc: PostgrestAPIError):
    # Most path/body IDs here (course_id, set_id, submission_id, ...) are
    # taken as plain strings and passed straight into a .eq("id", ...)
    # filter with no format check first — a malformed value (typo'd link,
    # probing tool) reaches Postgres as-is and raises 22P02 ("invalid input
    # syntax for type uuid"), which without this handler surfaced as a raw,
    # unhandled 500 instead of a clean 4xx. Any other Postgrest error still
    # comes back as a generic 500 — same outcome as before this handler
    # existed, just routed through this app's {"detail": ...} convention
    # instead of a bare unhandled-exception response.
    if exc.code == "22P02":
        return JSONResponse(status_code=400, content={"detail": "Invalid ID format."})
    print(f"[DB ERROR] {exc.code}: {exc.message}")
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})

# ─── Security response headers ───────────────────────────────────────────────
# None of these were set anywhere before — added conservatively (no CSP
# enforcement yet, since this API's /docs and /redoc pages plus the
# frontend's Razorpay checkout script would need real testing against a
# strict policy first; Report-Only mode surfaces violations without
# breaking anything while that testing happens).
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy-Report-Only"] = "default-src 'self'; frame-ancestors 'none'"
    return response


# ─── CORS ─────────────────────────────────────────────────────────────────────
# The extra localhost/127.0.0.1 fallback ports (for when 3000 is already
# taken and Next.js auto-increments) are only added when FRONTEND_URL
# itself is a localhost URL — i.e. this instance is actually being run
# against a local frontend — rather than gating on app_env, since APP_ENV
# is easy to leave stale in a local .env and FRONTEND_URL is the more
# direct signal of whether this is really a local environment.
_cors_origins = [settings.frontend_url]
if "localhost" in settings.frontend_url or "127.0.0.1" in settings.frontend_url:
    _cors_origins += [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(payments.router)
app.include_router(mcq.router)
app.include_router(sessions.router)
app.include_router(tests.router)
app.include_router(contact.router)
app.include_router(admin.router)
app.include_router(test_series.router)
app.include_router(coupons_router)
app.include_router(coupons_admin_router)
app.include_router(free_resources_router)
app.include_router(free_resources_admin_router)
app.include_router(mcq_import_router)


@app.get("/", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "service": "Caliber Education API",
        "version": "1.0.0",
        "docs": "/docs",
    }


# Render's health check is hitting the literal path "/." (not "/") on this
# deployment — most HTTP clients normalize away a trailing "/." dot-segment
# before sending the request, but whatever's probing here isn't, so it 404s
# forever and Render restart-loops the service. Answering "/." directly
# sidesteps needing to chase down which Render setting controls that path.
@app.get("/.", include_in_schema=False)
async def health_check_dot():
    return await health_check()
