-- ═══════════════════════════════════════════════════════════════════════════
-- Caliber Education — Free Resources Migration
-- Run ONCE in the Supabase SQL Editor. Safe to re-run: every statement is
-- idempotent (IF NOT EXISTS / DROP ... IF EXISTS).
--
-- Backs the public /free-resources page: per-subject links (Google Drive
-- folders, PDFs, ...) that admins add from Admin → Free Resources. Subjects
-- are the MCQ catalog's own (mcq_subjects), so the page lists every subject
-- the storefront sells, grouped by level, even before any link exists.
--
-- Purely additive: creates one new table and touches nothing else.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.free_resources (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Deleting a subject removes its links with it.
  subject_id  TEXT NOT NULL REFERENCES public.mcq_subjects(id) ON DELETE CASCADE,
  title       TEXT NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 120),
  -- Only http(s): these render as links on a public page, so a javascript:
  -- or data: URL must never get in. The backend validates this too.
  url         TEXT NOT NULL CHECK (url ~* '^https?://' AND char_length(url) <= 2000),
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_by  UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_free_resources_subject
  ON public.free_resources(subject_id, sort_order);

-- The backend uses the service-role client (which bypasses RLS); these
-- policies only matter for direct client access: anyone may read (the page
-- is public), only admins may write.
ALTER TABLE public.free_resources ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Anyone can view free resources" ON public.free_resources;
CREATE POLICY "Anyone can view free resources"
  ON public.free_resources FOR SELECT USING (true);

DROP POLICY IF EXISTS "Admins manage free resources" ON public.free_resources;
CREATE POLICY "Admins manage free resources"
  ON public.free_resources FOR ALL
  USING (public.is_admin()) WITH CHECK (public.is_admin());

-- To roll back (after removing the backend code that uses it):
--   DROP TABLE IF EXISTS public.free_resources;
