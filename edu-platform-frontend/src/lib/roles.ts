// Single source of truth for which roles enter the staff panel (/admin) and
// how each is labelled. These used to be five separate hardcoded lists —
// admin page, dashboard, Navbar (twice), post-login redirect — so adding a
// role meant finding all five, and missing one sent that role somewhere wrong.
//
// This only decides what the UI renders. Every admin API call is re-checked
// server-side (edu-platform-backend/app/dependencies.py), so nothing here
// grants access to anything.

export type Role = "student" | "mentor" | "admin" | "super_admin" | "mcq_editor";

const STAFF_PANEL_ROLES: ReadonlySet<string> = new Set(["admin", "super_admin", "mentor", "mcq_editor"]);

export function isStaffPanelRole(role: string | undefined): boolean {
  return !!role && STAFF_PANEL_ROLES.has(role);
}

export function staffRoleLabel(role: string | undefined): string {
  if (role === "mentor") return "Mentor";
  if (role === "mcq_editor") return "MCQ Editor";
  return "Admin";
}
