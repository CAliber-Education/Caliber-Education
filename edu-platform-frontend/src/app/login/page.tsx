"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "@/context/AuthContext";
import { AuthShell } from "@/components/AuthShell";
import { Turnstile } from "@/components/Turnstile";
import { getPostLoginRedirect } from "@/lib/authRedirect";
import { apiFetch, ApiFetchError } from "@/lib/apiFetch";
import { ArrowRight, CheckCircle, Eye, EyeOff, Loader2, Sparkles } from "lucide-react";

type Step = "form" | "done";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();

  // Course/MCQ/quiz/test-series pages send people here with ?next=<path> when
  // they try to buy or attempt something while logged out — previously this
  // was never read, so after logging in they always landed on the generic
  // dashboard instead of back where they were trying to go. Only accept a
  // genuine same-site relative path (starts with exactly one "/") so this
  // can't be turned into an open redirect via a crafted link.
  const nextPath = (() => {
    const raw = searchParams.get("next");
    if (raw && raw.startsWith("/") && !raw.startsWith("//")) return raw;
    return null;
  })();

  const [step, setStep] = useState<Step>("form");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  // AuthContext redirects here when a request comes back 401 for the
  // currently-stored session token (expired JWT, or signed in elsewhere) —
  // surface that instead of leaving the form blank with no explanation for
  // why the user is suddenly looking at a login page again. Checks
  // sessionStorage too, not just ?expired= — some pages have their own
  // logged-out redirect guard that can race AuthContext's and land on a
  // bare /login, dropping the query string.
  const [error, setError] = useState(() => {
    if (typeof window === "undefined") return "";
    const expired = searchParams.get("expired") || sessionStorage.getItem("caliber_session_expired");
    if (expired) sessionStorage.removeItem("caliber_session_expired");
    return expired ? "Your session expired. Please sign in again." : "";
  });
  const [turnstileToken, setTurnstileToken] = useState("");
  const [turnstileKey, setTurnstileKey] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);
  // True once a request has been in flight a while — most likely the free-tier
  // backend was asleep and is waking up (can take up to ~50s), not a real hang.
  const [slowHint, setSlowHint] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setError("Enter a valid email address."); return; }
    if (password.length < 1) { setError("Enter your password."); return; }
    if (!turnstileToken) {
      setError("Security verification in progress. Please wait.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    setSlowHint(false);
    const slowTimer = setTimeout(() => setSlowHint(true), 9000);
    try {
      // Call authentication login which is now mapped to backend POST payload
      const loggedInUser = await login(email, password, turnstileToken);
      setStep("done");
      setTimeout(() => router.push(nextPath || getPostLoginRedirect(loggedInUser.role)), 1400);
    } catch (err: any) {
      // Turnstile tokens are single-use — force a fresh widget so a retry
      // isn't doomed to fail bot-check with the already-spent token.
      setTurnstileToken("");
      setTurnstileKey((k) => k + 1);
      setError(err.message || "Invalid credentials.");
    } finally {
      clearTimeout(slowTimer);
      setIsSubmitting(false);
      setSlowHint(false);
    }
  }

  const handleGoogleAuth = async () => {
    setError("");
    setIsGoogleLoading(true);
    setSlowHint(false);
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const res = await apiFetch(`${apiURL}/api/auth/google/url`, { onSlow: () => setSlowHint(true) });
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
        return; // leaving the page — keep the button showing "loading" until navigation completes
      }
      setError("Failed to initialize Google connection.");
      setIsGoogleLoading(false);
      setSlowHint(false);
    } catch (err) {
      setError(err instanceof ApiFetchError ? err.message : "Failed to initialize Google connection.");
      setIsGoogleLoading(false);
      setSlowHint(false);
    }
  };

  return (
    <AuthShell progressStep={1} progressTotal={1}>
      <AnimatePresence mode="wait">
        {step === "done" ? (
          <motion.div key="done" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="text-center py-6 space-y-4">
            <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 300, damping: 20, delay: 0.1 }}
              className="w-16 h-16 rounded-lg border border-line-gray-light dark:border-line-gray-dark bg-line-gray-light/35 dark:bg-line-gray-dark/30 flex items-center justify-center mx-auto">
              <CheckCircle className="w-8 h-8 text-signal-emerald" />
            </motion.div>
            <div className="space-y-1">
              <h2 className="font-heading font-bold text-xl text-ink-navy dark:text-paper">Welcome back!</h2>
              <p className="text-xs text-slate dark:text-paper/60">Redirecting to your dashboard…</p>
            </div>
          </motion.div>
        ) : (
          <motion.div key="form" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.2 }} className="space-y-5">
            <div>
              <h2 className="font-heading font-bold text-xl text-ink-navy dark:text-paper">Sign in</h2>
              <p className="text-xs text-slate dark:text-paper/60 mt-1">Welcome back to CAliber.</p>
            </div>

            {/* Google is the primary, recommended path — one tap, nothing to
                remember. The manual form below still works exactly the same,
                just visually secondary. */}
            <div className="space-y-2">
              <button type="button" onClick={handleGoogleAuth} disabled={isGoogleLoading || isSubmitting}
                className="w-full flex items-center justify-center gap-2.5 py-3.5 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy font-bold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all text-sm shadow-sm disabled:opacity-60 disabled:cursor-not-allowed disabled:active:scale-100">
                {isGoogleLoading ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Connecting…</>
                ) : (
                  <>
                    <svg className="w-4.5 h-4.5" viewBox="0 0 24 24" style={{ width: 18, height: 18 }}>
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                    </svg>
                    Continue with Google
                  </>
                )}
              </button>
              <p className="flex items-center justify-center gap-1.5 text-[11px] text-signal-emerald font-semibold">
                <Sparkles className="w-3 h-3" /> Recommended — faster and more secure, no password to remember
              </p>
            </div>

            {slowHint && (
              <p className="text-center text-[11px] text-slate dark:text-paper/50 bg-line-gray-light/50 dark:bg-line-gray-dark/40 rounded-lg py-2 px-3">
                Still connecting — this can take up to a minute if our server was asleep.
              </p>
            )}

            <div className="relative flex items-center py-1">
              <div className="flex-grow border-t border-line-gray-light dark:border-line-gray-dark"></div>
              <span className="flex-shrink-0 mx-4 text-slate dark:text-paper/50 text-[10px] font-bold uppercase tracking-wider">or sign in with email</span>
              <div className="flex-grow border-t border-line-gray-light dark:border-line-gray-dark"></div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4 opacity-90">
              <div>
                <label htmlFor="login-email" className="text-[10px] font-bold uppercase tracking-wider text-slate dark:text-paper/70 mb-1.5 block">Email Address</label>
                <input id="login-email" type="email" placeholder="you@example.com" value={email}
                  onChange={(e) => { setEmail(e.target.value); setError(""); }}
                  className="w-full px-4 py-2.5 text-sm border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/50 text-ink-navy dark:text-paper rounded-lg focus:outline-none focus:border-ink-navy dark:focus:border-paper transition-colors" required />
              </div>
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label htmlFor="login-password" className="text-[10px] font-bold uppercase tracking-wider text-slate dark:text-paper/70">Password</label>
                  <Link href="/forgot-password" className="text-xs text-ink-navy dark:text-paper font-semibold hover:underline">Forgot password?</Link>
                </div>
                <div className="relative">
                  <input id="login-password" type={showPw ? "text" : "password"} placeholder="Your password" value={password}
                    onChange={(e) => { setPassword(e.target.value); setError(""); }}
                    className="w-full px-4 py-2.5 pr-10 text-sm border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/50 text-ink-navy dark:text-paper rounded-lg focus:outline-none focus:border-ink-navy dark:focus:border-paper transition-colors" required />
                  <button type="button" onClick={() => setShowPw(!showPw)} aria-label={showPw ? "Hide password" : "Show password"} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate/50 hover:text-slate transition-colors">
                    {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
              {error && <p className="text-xs text-alert-coral">{error}</p>}

              {/* Invisible Turnstile widget */}
              <Turnstile key={turnstileKey} onVerify={setTurnstileToken} />

              <button type="submit" disabled={isSubmitting || isGoogleLoading}
                className="w-full flex items-center justify-center gap-2 py-2.5 border border-line-gray-light dark:border-line-gray-dark text-ink-navy dark:text-paper font-semibold rounded-lg hover:bg-line-gray-light/40 dark:hover:bg-line-gray-dark/40 active:scale-[0.98] transition-all text-sm disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100">
                {isSubmitting ? <><Loader2 className="w-4 h-4 animate-spin" /> Signing in…</> : <>Sign In <ArrowRight className="w-4 h-4" /></>}
              </button>
            </form>

            <p className="text-xs text-center text-slate dark:text-paper/50 mt-4">
              New here?{" "}
              <Link href={nextPath ? `/signup?next=${encodeURIComponent(nextPath)}` : "/signup"} className="text-ink-navy dark:text-paper font-semibold hover:underline">Create an account</Link>
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </AuthShell>
  );
}

