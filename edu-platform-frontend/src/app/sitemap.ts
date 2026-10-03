import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

const STATIC_ROUTES = ["", "/about", "/courses", "/mcq", "/test-series", "/free-resources", "/terms"];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticEntries: MetadataRoute.Sitemap = STATIC_ROUTES.map((path) => ({
    url: `${SITE_URL}${path}`,
    lastModified: new Date(),
    changeFrequency: path === "" ? "daily" : "weekly",
    priority: path === "" ? 1 : 0.7,
  }));

  // Runs server-side at build/request time, not in the browser — call the
  // backend directly rather than going through the /api rewrite proxy
  // (which only exists for client-side requests).
  let courseEntries: MetadataRoute.Sitemap = [];
  try {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    const res = await fetch(`${backendUrl}/api/courses`, { next: { revalidate: 3600 } });
    if (res.ok) {
      const courses: { id: string }[] = await res.json();
      courseEntries = courses.map((c) => ({
        url: `${SITE_URL}/courses/${c.id}`,
        lastModified: new Date(),
        changeFrequency: "weekly",
        priority: 0.8,
      }));
    }
  } catch (e) {
    // Sitemap generation shouldn't fail the whole build if the backend is
    // briefly unreachable — just ship the static routes that time. Logged
    // so a silently course-less sitemap shows up in build output instead of
    // going unnoticed.
    console.error("[sitemap] Failed to fetch courses from backend, shipping static routes only:", e);
  }

  return [...staticEntries, ...courseEntries];
}
