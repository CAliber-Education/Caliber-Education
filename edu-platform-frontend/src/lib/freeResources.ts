// Shared by the public /free-resources page and Admin → Free Resources.
// Shapes mirror GET /api/free-resources (edu-platform-backend/app/routers/free_resources.py).

export type LevelCode = "FINAL" | "INTERMEDIATE" | "FOUNDATION";

export interface FreeResource {
  id: string;
  title: string;
  url: string;
}

export interface FreeResourceSubject {
  id: string;
  code: string;
  name: string;
  groupName: string;
  isActive?: boolean; // admin list only
  resources: FreeResource[];
}

export interface FreeResourceLevel {
  level: LevelCode;
  subjects: FreeResourceSubject[];
}

// Final first, matching the MCQ catalog's default level.
export const LEVEL_TABS: { level: LevelCode; label: string }[] = [
  { level: "FINAL", label: "CA Final" },
  { level: "INTERMEDIATE", label: "CA Inter" },
  { level: "FOUNDATION", label: "CA Foundation" },
];

export function groupLabel(groupName: string): string {
  if (groupName === "GROUP_1") return "Group I";
  if (groupName === "GROUP_2") return "Group II";
  return "";
}

export type LinkKind = "folder" | "file" | "video" | "link";

// The backend only stores http(s) links; checked again here before anything
// becomes an href, so a bad row can never render as a javascript: link.
export function isSafeUrl(url: string): boolean {
  return /^https?:\/\/[^\s]+$/i.test(url);
}

export function describeLink(url: string): { kind: LinkKind; label: string } {
  let host = "";
  let path = "";
  try {
    const parsed = new URL(url);
    host = parsed.hostname.replace(/^www\./, "");
    path = parsed.pathname;
  } catch {
    return { kind: "link", label: "Link" };
  }
  if (host === "drive.google.com") {
    if (path.includes("/folders/")) return { kind: "folder", label: "Google Drive folder" };
    if (path.includes("/file/")) return { kind: "file", label: "Google Drive file" };
    return { kind: "folder", label: "Google Drive" };
  }
  if (host === "docs.google.com") return { kind: "file", label: "Google Docs" };
  if (host === "youtube.com" || host === "m.youtube.com" || host === "youtu.be") return { kind: "video", label: "YouTube" };
  if (/\.pdf($|\?)/i.test(path)) return { kind: "file", label: `PDF · ${host}` };
  return { kind: "link", label: host };
}
