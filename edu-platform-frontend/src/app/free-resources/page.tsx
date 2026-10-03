import type { Metadata } from "next";
import FreeResourcesClient, { type FreeResourceLevel } from "./FreeResourcesClient";

export const metadata: Metadata = {
  title: "Free CA Study Resources — Foundation, Intermediate & Final",
  description:
    "Free notes, question banks and past papers for every CA Foundation, Intermediate and Final subject.",
  alternates: { canonical: "/free-resources" },
};

// Runs server-side, calling the backend directly like mcq/page.tsx, so the
// subject list ships in the initial HTML. Revalidates every minute: links an
// admin adds show up within about a minute without a redeploy.
async function getFreeResources(): Promise<FreeResourceLevel[] | null> {
  try {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    const res = await fetch(`${backendUrl}/api/free-resources`, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    const data = await res.json();
    return Array.isArray(data.levels) ? data.levels : null;
  } catch {
    return null;
  }
}

export default async function FreeResourcesPage() {
  const levels = await getFreeResources();
  return <FreeResourcesClient levels={levels} />;
}
