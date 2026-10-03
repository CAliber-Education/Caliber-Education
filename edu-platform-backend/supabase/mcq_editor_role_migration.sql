-- ═══════════════════════════════════════════════════════════════════════════
-- Caliber Education — MCQ Editor Role Migration
-- Run ONCE in the Supabase SQL Editor. Safe to re-run: every statement is
-- idempotent (DROP ... IF EXISTS / ADD COLUMN IF NOT EXISTS / IF NOT EXISTS).
--
-- Adds a content-only `mcq_editor` role: someone who can author MCQ papers in
-- the hierarchy and nothing else — no users, payments, coupons, sessions, or
-- any other admin-panel data. Enforcement lives in the backend
-- (app/routers/admin.py, require_mcq_author); this migration only makes the
-- role storable and gives papers an owner so editors can be scoped to their
-- own work.
--
-- Both changes are purely additive. No existing row is modified, no existing
-- role loses access, and nothing is rewritten — adding a nullable column with
-- no default is a metadata-only change in Postgres, so it does not lock or
-- rewrite mcq_papers.
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── 1. Allow the new role value ─────────────────────────────────────────────
-- Same constraint as production_hardening_migration.sql, with 'mcq_editor'
-- appended. Every value that was valid before is still valid.

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_role_check;
ALTER TABLE public.profiles ADD CONSTRAINT profiles_role_check
  CHECK (role = ANY (ARRAY[
    'student'::text, 'mentor'::text, 'admin'::text, 'super_admin'::text,
    'mcq_editor'::text
  ]));


-- ─── 2. Paper ownership ──────────────────────────────────────────────────────
-- Who created each paper. An mcq_editor may only see, edit, and delete papers
-- where created_by is themselves. Every paper that exists today gets NULL,
-- which no editor can ever match — so all current papers stay admin-only
-- without any backfill.
--
-- ON DELETE SET NULL: deleting the editor's account keeps their papers (they
-- may already be published to students) and simply hands them back to
-- admin-only ownership.

ALTER TABLE public.mcq_papers
  ADD COLUMN IF NOT EXISTS created_by UUID
  REFERENCES public.profiles(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_mcq_papers_created_by ON public.mcq_papers(created_by);


-- ═══════════════════════════════════════════════════════════════════════════
-- Granting the role is done here in the SQL editor (there is deliberately no
-- button for it in the admin panel). The person must already have signed up:
--   UPDATE public.profiles SET role = 'mcq_editor' WHERE lower(email) = lower('person@example.com');
-- Removing it:
--   UPDATE public.profiles SET role = 'student' WHERE lower(email) = lower('person@example.com');
-- The person must log out and back in for the panel to pick up the change.
--
-- To roll back (only after reverting the backend code that references it):
--   UPDATE public.profiles SET role = 'student' WHERE role = 'mcq_editor';
--   ALTER TABLE public.mcq_papers DROP COLUMN IF EXISTS created_by;
--   -- then re-run section 1 of production_hardening_migration.sql
-- ═══════════════════════════════════════════════════════════════════════════
