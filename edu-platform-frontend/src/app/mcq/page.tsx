import type { Metadata } from "next";
import MCQClient from "./MCQClient";
import { MCQSubject, MCQBundle, normalizeMCQSubject, normalizeMCQBundle } from "@/lib/mcqPricingData";

export const metadata: Metadata = {
  title: "CA MCQ Practice — Foundation, Intermediate & Final",
  description:
    "Timed MCQ practice sets for CA Foundation, Intermediate & Final, built to mirror the real exam pattern with full explanations for every question.",
  alternates: { canonical: "/mcq" },
};

// Runs server-side — call the backend directly rather than through the
// client-only /api rewrite proxy, same pattern as courses/page.tsx. Ships
// the subject/bundle catalog in the initial HTML for SEO instead of
// leaving it to a client-side fetch on mount; MCQClient falls back to its
// seeded pricing matrix if both of these come back empty.
async function getMCQPackages(): Promise<{ subjects: MCQSubject[]; bundles: MCQBundle[] }> {
  try {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    const res = await fetch(`${backendUrl}/api/mcq/packages`, { next: { revalidate: 300 } });
    if (!res.ok) return { subjects: [], bundles: [] };
    const data = await res.json();
    return {
      subjects: Array.isArray(data.allSubjects) ? data.allSubjects.map(normalizeMCQSubject) : [],
      bundles: Array.isArray(data.allBundles) ? data.allBundles.map(normalizeMCQBundle) : [],
    };
  } catch {
    return { subjects: [], bundles: [] };
  }
}

export default async function MCQPage() {
  const { subjects, bundles } = await getMCQPackages();
  return <MCQClient initialSubjects={subjects} initialBundles={bundles} />;
}
