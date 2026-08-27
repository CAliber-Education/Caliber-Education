// Single source of truth for the site's canonical URL/name/description —
// layout.tsx, robots.ts, sitemap.ts, and courses/[id]/page.tsx all import
// SITE_URL from here rather than each holding their own literal, so a
// domain change is a one-line edit instead of a repo-wide find-and-replace.
//
// Reads NEXT_PUBLIC_SITE_URL so the eventual custom domain is a Vercel env
// var change, not a code change — the fallback tracks whichever host is
// actually live (currently Vercel; the netlify.toml in this repo is a
// leftover from an earlier, no-longer-served deployment target, confirmed
// by diffing content served from each host). Update the fallback if the
// live host changes again before the custom domain is set.
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://caliber-education.vercel.app";
export const SITE_NAME = "CAliber Education";
export const SITE_DESCRIPTION =
  "Premium MCQ practice platform for CA Foundation, Intermediate & Final droppers. Timed mock sets, detailed explanations, mentor-led test series, and WhatsApp group access.";
