-- ═══════════════════════════════════════════════════════════════════════════
-- Caliber Education — All India Scholarship Test
-- Run ONCE in the Supabase SQL Editor. Safe to re-run.
--
-- A scholarship test is an MCQ paper with is_scholarship = true. Students pay
-- for it once, take it once, and see "result coming soon" instead of their
-- marks. Admins rank everyone in Admin → Leaderboard and publish the results
-- (results_published_at), after which each student sees their rank, marks
-- and which answers were right or wrong in their dashboard.
--
-- Purely additive: two new columns on mcq_papers, nothing else changes.
-- ═══════════════════════════════════════════════════════════════════════════

  ALTER TABLE public.mcq_papers
    ADD COLUMN IF NOT EXISTS is_scholarship BOOLEAN NOT NULL DEFAULT false;
  
  -- NULL until an admin publishes the results.
  ALTER TABLE public.mcq_papers
    ADD COLUMN IF NOT EXISTS results_published_at TIMESTAMPTZ;
