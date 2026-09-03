"use client";

import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";
import { apiFetch } from "@/lib/apiFetch";

interface User {
  id: string;
  email: string;
  role: "student" | "mentor" | "admin" | "super_admin";
  profileComplete: boolean;
}

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isMounted: boolean;
  login: (email: string, password?: string, turnstileToken?: string) => Promise<User>;
  setSession: (token: string, user: User) => void;
  logout: () => void;
  markProfileComplete: () => void;
  purchasedCourseIds: string[];
  refreshPurchases: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Patches window.fetch exactly once (module scope, not per-provider-mount —
// React 18 Strict Mode double-invokes effects in dev, and this must never
// double-wrap) so any request carrying the CURRENT session's JWT that comes
// back 401 fires a global event. Comparing the request's Authorization
// header against the live localStorage token — not just "any 401" — is
// what keeps this from misfiring on login/signup's own expected 401s
// (wrong password, expired OTP code, expired signup temp-token): none of
// those ever send the real session token, since the user isn't logged in
// yet at that point.
let authFetchPatched = false;
function ensureAuthFetchInterceptor() {
  if (authFetchPatched || typeof window === "undefined") return;
  authFetchPatched = true;
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args: Parameters<typeof fetch>) => {
    const response = await originalFetch(...args);
    if (response.status === 401) {
      try {
        const init = args[1];
        const headers = new Headers(init?.headers);
        const authHeader = headers.get("Authorization");
        const currentToken = localStorage.getItem("caliber_jwt");
        if (authHeader && currentToken && authHeader === `Bearer ${currentToken}`) {
          window.dispatchEvent(new Event("caliber:session-expired"));
        }
      } catch {
        // Never let interceptor bookkeeping break the real response.
      }
    }
    return response;
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [purchasedCourseIds, setPurchasedCourseIds] = useState<string[]>([]);
  const [mounted, setMounted] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  // Auto-logout the moment the backend rejects the current session's own
  // token (expired JWT, or the "signed in on another device" concurrent-
  // session check) — previously every API call just failed silently and
  // the UI kept showing the user as logged in until they refreshed.
  useEffect(() => {
    ensureAuthFetchInterceptor();
    const handleExpired = () => {
      setUser(null);
      localStorage.removeItem("caliber_user");
      localStorage.removeItem("caliber_jwt");
      // Some pages have their own "redirect to /login if logged out" guard
      // that fires right after setUser(null) above and races this push,
      // sometimes winning and dropping the ?expired= query string — a
      // sessionStorage flag survives that race regardless of which
      // redirect's URL actually lands, so the login page still knows why
      // it's showing.
      sessionStorage.setItem("caliber_session_expired", "1");
      const next = pathname && pathname !== "/login" ? `&next=${encodeURIComponent(pathname)}` : "";
      router.push(`/login?expired=1${next}`);
    };
    window.addEventListener("caliber:session-expired", handleExpired);
    return () => window.removeEventListener("caliber:session-expired", handleExpired);
  }, [router, pathname]);

  // Load from localStorage on mount
  useEffect(() => {
    const savedUser = localStorage.getItem("caliber_user");
    if (savedUser) {
      setUser(JSON.parse(savedUser));
    }
    setMounted(true);
  }, []);

  // Save changes to localStorage
  useEffect(() => {
    if (!mounted) return;
    if (user) {
      localStorage.setItem("caliber_user", JSON.stringify(user));
    } else {
      localStorage.removeItem("caliber_user");
    }
  }, [user, mounted]);

  // Real, backend-verified course enrolments (Razorpay purchases + free
  // enrolments, both stored in the `enrollments` table) — the only source
  // of truth for "which courses does this user actually own". Re-fetchable
  // on demand via refreshPurchases() so pages can pull in a just-completed
  // purchase immediately instead of waiting for the next login/mount.
  const refreshPurchases = async () => {
    if (!user) { setPurchasedCourseIds([]); return; }
    const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
    const token = localStorage.getItem("caliber_jwt") || "";
    if (!token) { setPurchasedCourseIds([]); return; }
    try {
      const res = await fetch(`${apiURL}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
      const data = res.ok ? await res.json() : null;
      setPurchasedCourseIds(data?.purchases || []);
    } catch {
      setPurchasedCourseIds([]);
    }
  };

  useEffect(() => {
    if (!mounted) return;
    refreshPurchases();
  }, [user, mounted]);

  const login = async (email: string, password?: string, turnstileToken?: string) => {
    const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
    try {
      const res = await apiFetch(`${apiURL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, turnstileToken }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        // FastAPI's HTTPException body is {"detail": "..."}, not {"error": "..."}
        throw new Error(err.detail || "Login failed");
      }
      const data = await res.json();
      if (data.token) {
        localStorage.setItem("caliber_jwt", data.token);
      }
      setUser(data.user);
      return data.user;
    } catch (err: any) {
      // No mock-user fallback: a failed login must surface as a failed
      // login, not silently sign the caller in (this previously let anyone
      // become an "admin" locally just by having "admin" in their email).
      throw err;
    }
  };

  // Hydrate the session directly from a token+user pair a backend call
  // already returned (e.g. register's response) — skips a second network
  // round trip, and avoids reusing a single-use Turnstile token twice.
  const setSession = (token: string, sessionUser: User) => {
    localStorage.setItem("caliber_jwt", token);
    setUser(sessionUser);
  };

  const logout = () => {
    // Best-effort — invalidates the JWT server-side (rotates
    // profiles.active_session_id) so it can't be reused after logout, but a
    // network failure here must never block the local sign-out below.
    const token = localStorage.getItem("caliber_jwt");
    if (token) {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      fetch(`${apiURL}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => { /* local sign-out still proceeds below */ });
    }
    setUser(null);
    localStorage.removeItem("caliber_user");
    localStorage.removeItem("caliber_jwt");
  };

  const markProfileComplete = () => {
    setUser((prev) => (prev ? { ...prev, profileComplete: true } : prev));
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isMounted: mounted,
        login,
        setSession,
        logout,
        markProfileComplete,
        purchasedCourseIds,
        refreshPurchases,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
