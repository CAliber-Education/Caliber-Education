import type { Metadata } from "next";
import CoursesClient from "./CoursesClient";
import { type Course } from "@/lib/mockData";

export const metadata: Metadata = {
  title: "CA Foundation, Intermediate & Final Courses",
  description:
    "Browse CA Foundation, Intermediate & Final courses on CAliber Education — structured for droppers and repeaters, with mentor support and exam-pattern practice built in.",
  alternates: { canonical: "/courses" },
};

// Runs server-side — call the backend directly rather than through the
// client-only /api rewrite proxy, same pattern as courses/[id]/page.tsx and
// sitemap.ts. Ships the public catalog in the initial HTML for SEO instead
// of leaving it to a client-side fetch on mount.
async function getCourses(): Promise<Course[]> {
  try {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    const res = await fetch(`${backendUrl}/api/courses`, { next: { revalidate: 300 } });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export default async function CoursesPage() {
  const initialCourses = await getCourses();
  return <CoursesClient initialCourses={initialCourses} />;
}
