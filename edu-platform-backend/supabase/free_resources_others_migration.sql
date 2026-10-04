-- ═══════════════════════════════════════════════════════════════════════════
-- Caliber Education — Free Resources: "Others" + Foundation Accounting / Laws
-- Run ONCE in the Supabase SQL Editor, after free_resources_migration.sql.
-- Safe to re-run.
--
-- Free Resources now also lists entries that aren't MCQ subjects: an
-- "Others" section in every level, and CA Foundation's Accounting and
-- Business Laws (which have no MCQ product). They're defined in the backend
-- (EXTRA_SUBJECTS in app/routers/free_resources.py), so links for them can't
-- point at a row in mcq_subjects. This drops that one foreign key; nothing
-- else changes and no data is touched.
--
-- Deleting an MCQ subject no longer deletes its links automatically; they
-- simply stop showing (the page only lists subjects that exist).
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE public.free_resources
  DROP CONSTRAINT IF EXISTS free_resources_subject_id_fkey;
