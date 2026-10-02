# Caliber Education — Production Deployment Readiness Report

**Audit date:** 2026-08-08
**Scope:** Full read-only review of `edu-platform-frontend` + `edu-platform-backend` — security, scalability, git/secret hygiene, and deployment configuration. No code was changed as part of this audit (except this file).

## Executive summary

**Not yet ready to go live for real payments.** Two things block that specifically:

1. A real (test-mode) Razorpay secret key is committed to your GitHub repo in a markdown file.
2. Your production `.env` is configured with Razorpay **test-mode** keys — right now, even in `APP_ENV=production`, no real money can be collected. Every "purchase" tonight has been a sandbox transaction.

Beyond those two, the codebase itself is in solid shape — auth, CORS, secrets hygiene (aside from the one leak below), and dependency versions are all good. The real remaining work is: rotate/scrub the leaked key, switch to live Razorpay keys when you're ready to actually charge people, confirm your database schema is fully up to date (see the migration section — this is the part I genuinely cannot verify from outside), and fix two real payment-integrity bugs before this is exposed to the public at scale.

**Build check (2026-08-08, this pass):** both apps build clean with tonight's latest changes — frontend `next build` (TypeScript + all 21 routes) and backend `py_compile` + full app import (131 routes) both pass with zero errors. `pip check` reports no dependency conflicts. Safe to deploy from the current working tree once the items below are addressed.

---

## Your stack: Render (backend, free) + Vercel (frontend, already deployed) + Supabase (DB)

Good choice for a free, ~100-200-user startup launch — all three have workable free tiers and your backend is already stateless (no in-memory session data that would break on restarts), so this combination will work correctly. Two things specific to this stack you need to know about:

**1. Render's free tier sleeps after 15 minutes of inactivity.** The first request after an idle period takes 30-60 seconds to wake the backend back up — a real visitor hitting a cold instance will see a long hang on their first page load (login, signup, anything that calls the API). This won't corrupt any data (your backend has no state that depends on staying warm), it's purely a latency/UX issue. **Cheap fix:** once you add the `/health` endpoint (checklist below), point a free external uptime pinger (UptimeRobot, cron-job.org, or similar — all have free tiers) at it every 10-14 minutes to keep the instance from sleeping. At 100-200 users this is a completely reasonable way to run for free; revisit if you outgrow it.

**2. `NEXT_PUBLIC_*` env vars are baked in at Vercel build time, not read live.** Since your backend isn't deployed yet, your live Vercel frontend is currently pointing `NEXT_PUBLIC_API_URL` at whatever placeholder/localhost value it had at last build — it won't work against a real backend until you update that env var in Vercel's dashboard **and trigger a new deploy** (changing the env var alone does nothing until the next build). Same applies to `NEXT_PUBLIC_RAZORPAY_KEY_ID` and `NEXT_PUBLIC_TURNSTILE_SITE_KEY`.

**Render setup specifics:**
- Create a new **Web Service** on Render, connect your GitHub repo, set root directory to `edu-platform-backend`.
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` — **use `$PORT`, not the hardcoded `8000`** from the Dockerfile. Render assigns the port dynamically and your app must bind to whatever it provides; if you deploy the existing Dockerfile as-is instead of Render's native Python runtime, override the start command in Render's dashboard to respect `$PORT` rather than relying on the Dockerfile's fixed `--port 8000`.
- Add every backend env var from the checklist below in Render's dashboard (Environment tab) — none of them carry over from your local `.env` automatically.
- Once deployed, you'll have a URL like `https://your-service.onrender.com` — this becomes your `BACKEND_URL` in Vercel (see section 5's note — `NEXT_PUBLIC_API_URL` should stay empty), your webhook base URL in Razorpay, and your `BACKEND_URL` GitHub Actions secret.

At 100-200 users, none of the scalability findings below (blocking Supabase calls on a single worker, in-memory rate limiter) are likely to actually bite you — they're real findings for when you outgrow this stage, not blockers for launch. I've left them in the report below so they're documented, but don't let them slow down shipping at this scale.

---

## 🔴 Critical — fix before going live

### 1. Leaked Razorpay secret key, committed to GitHub tonight
`edu-platform-frontend/TEST_MODE_MCQ_EXTENSION.md` (introduced in commit `5794f9c`, pushed to `origin/master` tonight) contains:
```
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=<real value — matches your current .env exactly>
```
I compared it against your live `.env` — **it's the real value**, not a placeholder. This is a `rzp_test_` (sandbox) key, not a live/production key, so no real money is at risk from this specific leak *today* — but it's still a live credential sitting in your git history, and if this repo is or ever becomes public, anyone can find it in minutes.

**What to do:**
- Rotate this key now regardless (Razorpay dashboard → Settings → API Keys → regenerate test key), and update your local `.env` with the new value.
- Delete `edu-platform-frontend/TEST_MODE_MCQ_EXTENSION.md` from the repo (I can do this — just say the word). Deleting it in a new commit stops it appearing going forward, but the old value stays recoverable in git history; since you're rotating the key anyway, that becomes moot.
- Going forward: never paste real key values into markdown docs, even "for reference" — always placeholder them.

### 2. Payment gateway is in test mode, not live
`RAZORPAY_KEY_ID` in your backend `.env` starts with `rzp_test_`. Until you swap in your **live** Razorpay keys (`rzp_live_...`), no real customer payment will ever actually charge a card — everything routes through Razorpay's sandbox. This is expected during development, but it's the single most important checkbox before announcing this is "live."

**What to do:** Get your live API keys from Razorpay (requires their KYC/activation process if not already done), set `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` in production `.env`, set `NEXT_PUBLIC_RAZORPAY_KEY_ID` in the frontend's production env, and confirm `RAZORPAY_WEBHOOK_SECRET` is configured for the live webhook endpoint in Razorpay's dashboard (not just the test one).

### 3. `ALLOW_TEST_PAYMENTS=true` in your production `.env`
Flagged earlier tonight, still unresolved (I didn't touch it per your instruction not to edit `.env`). This flag enables `mock-confirm*` endpoints that let an admin account grant themselves free access without paying. **Flip this to `false`** in production once you're done testing.

### 4. Payment verification isn't idempotent — replayable for free access
`verify-payment` and `verify-mcq-payment` (`edu-platform-backend/app/routers/payments.py`) don't check whether a payment was already approved before granting access. Unlike your Razorpay webhook handler (which correctly no-ops on an already-approved payment), these two endpoints will happily re-run the grant logic every time they're called with the same valid signature — and your enrollment-extension logic *stacks* additional access time on each call. A student who captures one valid request (e.g. via browser devtools) can replay it repeatedly to keep extending their own access for free, with no repeat payment. This needs the same "already approved → no-op" guard the webhook already has.

### 5. MCQ answer key exposed for unpurchased papers
`POST /api/quizzes/{set_id}/submit-v2` (`edu-platform-backend/app/routers/mcq.py`) never checks whether the student actually has access to that paper before returning the answer key and explanations — the ownership check exists on the "start quiz" endpoint but not on submit. Anyone logged in can POST guessed answers directly to a locked, paid paper's ID and get the full answer key back without buying it.

### 6. Leaderboard/score data can be fabricated
A legacy endpoint (`POST /api/quizzes/{set_id}/attempts` in `mcq.py`) writes whatever `score`/`total` the client sends straight into the attempts table, which feeds the leaderboard. Lower severity than the above two (no money/access bypass), but worth closing before this is public — students could top the leaderboard by lying.

### 7. Database migration state is unverifiable from here
Your `edu-platform-backend/supabase/` folder has **19 SQL files** with no numbering system and no single source of truth for what's actually been run against your live database — only partial ordering hints in a few file headers. Two of them (`mcq_v3_hierarchy_migration.sql` and `mcq_v3_ca_hierarchy_migration.sql`) look like two versions of the same migration, and the second one **drops tables** — running the wrong one, or running it twice, against live data would be destructive. I don't have a direct database connection (only the service-role REST API), so I genuinely cannot tell you which of these have already been applied. **You need to personally confirm** — either by checking Supabase's SQL history/logs, or by reviewing each file against your current live schema — before this app is deployed fresh anywhere (a new environment, a teammate's machine, disaster recovery, etc.), since a fresh deploy has no way to know what state your existing production database is already in.

---

## 🟠 High priority — fix before or shortly after launch

- **Blocking concurrency bug**: every backend route is declared `async def`, but the actual Supabase calls inside them are synchronous/blocking, and the server runs as a single uvicorn worker with no `--workers` flag. In practice this means the whole backend can only make progress on **one** database call at a time — every other user's request (even unrelated ones) queues up behind it. This is the top real scalability risk and will show up as slowness under normal traffic, not just at scale. Fix: either move blocking Supabase calls off the event loop (`run_in_threadpool`), or run multiple uvicorn workers (`--workers N`) — the second is the faster fix for now.
- **Rate limiter is in-memory**, not shared (no Redis backend). Fine for a single instance; if you ever scale to multiple backend instances or add `--workers`, rate limits become bypassable by hitting a different process. Worth knowing now so it doesn't surprise you later.
- **No health check endpoint** (`/health`) and **no error monitoring** (no Sentry or equivalent anywhere). You'll be flying blind on production errors until a user reports one.
- **File upload paths use the raw uploaded filename** (`tests.py`, `admin.py`) — not a traversal risk against your Storage bucket, but a user-controlled filename with slashes in it could land in an unexpected sub-path. Cheap fix: strip/replace path separators before building the storage key.
- The repo also has Docker config (`Dockerfile`s, `docker-compose.yml`) for both apps — now that you've settled on Render + Vercel, these aren't needed for deployment; harmless to keep around for local testing, or delete later if you want a cleaner repo.
- **`/docs` and `/redoc`** (full API schema) are publicly reachable with no gating — your call whether that's intentional for a consumer-facing app.

## 🟡 Medium priority — fix soon after launch, not blocking

- Several sensitive endpoints have no rate limiting: the `verify-*-payment` endpoints, MCQ submit, session booking, test submission. Lower urgency than the auth/payment-creation endpoints that already have it, but worth adding.
- One error handler (`payments.py`, Razorpay order creation) returns the raw exception message to the client — minor internal-detail leak, not sensitive data.
- N+1 query pattern in the public MCQ catalog endpoint (`mcq.py`) — extra Supabase round-trips per paper shown. Not urgent at your current catalog size, but will slow down as it grows.
- Email sending during payment verification is synchronous and blocks the response (compounds the concurrency issue above).

## ✅ What's already solid — no action needed

- No secrets in your `.env` files ever reach git (checked history, not just current state) — the one leak above is the sole exception, and it's a documentation file, not `.env`.
- Every admin endpoint (67 checked) correctly requires `require_admin`/`require_super_admin`/`require_mentor`.
- CORS is a real origin whitelist, not a wildcard.
- Razorpay payment *signature* verification and webhook HMAC verification are both done correctly (constant-time comparison, no bypass path).
- JWT handling is sound — no algorithm-confusion risk, secret is required (won't silently start without one), expiry is enforced.
- No raw SQL string-building anywhere — everything goes through the parameterized query builder.
- Dependencies are current (FastAPI, Next.js 16, React 19, Supabase client — nothing alarmingly outdated).
- `next/image` is used consistently; no unoptimized raw `<img>` tags anywhere in the frontend.
- Your `FRONTEND_URL`/CORS setup is already environment-configurable — pointing this at your real domain in production needs an env var change, not a code change.

---

## Git repository review

- No `.env` file has ever been tracked, in current state or in full history — confirmed clean.
- One leaked secret, addressed above (item 1).
- You have **uncommitted local changes right now** from tonight's last two rounds of fixes (already-purchased detection, bundle coupon support) — not pushed yet. Commit and push these when you're ready.
- `node_modules/`, `.next/`, build artifacts are correctly gitignored.
- A handful of internal status/planning docs (`CURRENT_STATUS_FINAL.md`, `PAYMENT_STATUS.md`, `case_based_mcq_plan.md`, etc.) are tracked in the repo root — harmless, just development notes; consider moving them to a `/docs` folder or `.gitignore`-ing them if you'd rather keep the root clean, but no security concern either way.

---

## Deployment checklist — step by step

### 1. Secrets and payment cutover
- [ ] Rotate the leaked Razorpay test secret key (Critical #1)
- [ ] Delete `TEST_MODE_MCQ_EXTENSION.md` from the repo (ask me to do this, or do it yourself)
- [ ] Obtain live Razorpay API keys (requires Razorpay KYC/activation if not done)
- [ ] Set `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` to live values in production backend env
- [ ] Set `NEXT_PUBLIC_RAZORPAY_KEY_ID` to the live key in production frontend env
- [ ] Configure `RAZORPAY_WEBHOOK_SECRET` for your live webhook endpoint in Razorpay's dashboard
- [ ] Set `ALLOW_TEST_PAYMENTS=false` in production
- [ ] Configure Supabase custom SMTP (from earlier tonight's audit) so OTP emails aren't capped at the shared 30/hour limit

### 2. Database
- [ ] Personally confirm which SQL migrations in `edu-platform-backend/supabase/` have already been applied to your live Supabase project (I cannot verify this remotely)
- [ ] Resolve the `mcq_v3_hierarchy_migration.sql` vs `mcq_v3_ca_hierarchy_migration.sql` duplication — confirm only the correct one was ever run, and never run the table-dropping one again against live data
- [ ] Confirm the two Storage buckets (`test-submissions`, `evaluated-papers`, or your configured names) exist in production Supabase
- [ ] Take a manual Supabase backup/snapshot before any further schema changes, as a safety net

### 3. Hosting (decided: Render + Vercel + Supabase)
- [ ] Create the Render Web Service (root dir `edu-platform-backend`, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
- [ ] Set every backend env var from the checklist below in Render's dashboard
- [ ] Set every frontend env var from the checklist below in Vercel's dashboard. **Updated since this report was written:** `next.config.ts` now proxies `/api/*` to the backend server-side via a `BACKEND_URL` env var (set that to your Render URL in Vercel) rather than the browser calling the backend directly — leave `NEXT_PUBLIC_API_URL` **empty** in production so requests stay same-origin through the proxy. Only fall back to setting `NEXT_PUBLIC_API_URL` directly if you deliberately switch away from the rewrite-proxy pattern, and if you do, make sure the backend's CORS allow-list actually includes your Vercel domain.
- [ ] Trigger a fresh Vercel deploy after updating env vars — they don't apply until the next build
- [ ] Set `FRONTEND_URL` in Render's env vars to your real Vercel domain
- [ ] Add a `/health` endpoint and point a free uptime pinger (UptimeRobot / cron-job.org) at it every 10-14 min so Render's free tier doesn't sleep between visits

### 4. Backend environment variables to configure
| Variable | Purpose |
|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Database/auth access |
| `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_DAYS` | Login token signing |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Payments |
| `TURNSTILE_SECRET_KEY` | Bot-check on auth/contact forms |
| `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL` | Transactional email |
| `CONTACT_NOTIFICATION_EMAIL` | Where contact-form messages go |
| `SUPABASE_SUBMISSION_BUCKET`, `SUPABASE_EVALUATION_BUCKET` | Storage bucket names |
| `MAINTENANCE_SECRET` | Authenticates the daily file-purge cron |
| `FRONTEND_URL` | CORS allow-list / email links |
| `APP_ENV` | Must be `production` |
| `ALLOW_TEST_PAYMENTS` | Must be `false` |

### 5. Frontend environment variables to configure
| Variable | Purpose |
|---|---|
| `BACKEND_URL` | Backend base URL — server-side only, used by the `/api/*` rewrite proxy in `next.config.ts`. This is the one that must point at your Render URL. |
| `NEXT_PUBLIC_API_URL` | Leave **empty** in production (see note in section 3) — only set this if you deliberately bypass the rewrite proxy |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | Cloudflare Turnstile (public half) |
| `NEXT_PUBLIC_RAZORPAY_KEY_ID` | Razorpay checkout (public half) |
| `NEXT_PUBLIC_ENABLE_TEST_PAYMENTS` | Must be unset/false in production |

### 6. GitHub Actions
- [ ] Set `BACKEND_URL` repo secret to your Render service URL, and `MAINTENANCE_SECRET` matching what you set in Render, so the daily purge-cron (`.github/workflows/purge-old-files.yml`) can reach production

### 7. Fix before public traffic
- [ ] Payment verification idempotency guard (Critical #4)
- [ ] MCQ submit-v2 access check (Critical #5)
- [ ] Legacy attempts endpoint trusting client score (Critical #6)
- [ ] Decide on `/docs`/`/redoc` public exposure

### 8. Observability
- [ ] Add a `/health` endpoint for your hosting provider's health checks
- [ ] Wire up basic error tracking (Sentry or similar) so you find out about production errors before your users tell you

### 9. Final pre-launch pass
- [ ] Commit and push tonight's uncommitted changes
- [ ] Do one real, live-mode Razorpay test purchase end to end before announcing launch
- [ ] Confirm the OTP email flow works with custom SMTP configured (not the rate-limited default)
