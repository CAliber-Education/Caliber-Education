"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { Award, Clock, FileText, Hourglass, CheckCircle2, ArrowRight, CreditCard, Trophy } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { Toast, type ToastState } from "@/components/Toast";
import { UpiPaymentModal, type UpiSubmitDetails } from "@/components/UpiPaymentModal";
import type { ScholarshipStatus, ScholarshipTest } from "@/lib/scholarship";

const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
const paymentMode = process.env.NEXT_PUBLIC_PAYMENT_MODE || "manual";

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("caliber_jwt") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface RazorpayResponse { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }
interface RazorpayInstance { open(): void; on(event: string, cb: () => void): void }
type RazorpayCtor = new (options: Record<string, unknown>) => RazorpayInstance;
const razorpayGlobal = () => (window as unknown as { Razorpay?: RazorpayCtor }).Razorpay;

async function loadRazorpay(): Promise<RazorpayCtor> {
  const existing = razorpayGlobal();
  if (existing) return existing;
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Razorpay SDK"));
    document.body.appendChild(script);
  });
  const loaded = razorpayGlobal();
  if (!loaded) throw new Error("Razorpay SDK unavailable");
  return loaded;
}

// All India Scholarship Test on the MCQ page: register (pay once), take it
// once, then wait for results to be published. One hook holds the data and
// payment flow; the banner and the catalog card both render from it.
export function useScholarship() {
  const router = useRouter();
  const { isAuthenticated } = useAuth();
  const [tests, setTests] = useState<ScholarshipTest[]>([]);
  const [status, setStatus] = useState<Record<string, ScholarshipStatus>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [upiFor, setUpiFor] = useState<ScholarshipTest | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  // Bumped after a payment so the card picks up the new registration.
  const [statusKey, setStatusKey] = useState(0);
  const loadStatus = () => setStatusKey((k) => k + 1);

  useEffect(() => {
    fetch(`${apiURL}/api/scholarship-tests`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setTests)
      .catch(() => setTests([]));
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return; // logged-out visitors just see the price
    let cancelled = false;
    fetch(`${apiURL}/api/scholarship-tests/mine`, { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (data && !cancelled) setStatus(data); })
      .catch(() => { /* cards still work, just without the personal state */ });
    return () => { cancelled = true; };
  }, [isAuthenticated, statusKey]);

  function requireLogin() {
    router.push("/login?next=/mcq");
  }

  async function payWithRazorpay(t: ScholarshipTest) {
    if (!isAuthenticated) return requireLogin();
    setBusyId(t.id);
    try {
      const orderRes = await fetch(`${apiURL}/api/payments/create-scholarship-order`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ paperId: t.id }),
      });
      const order = await orderRes.json().catch(() => ({}));
      if (!orderRes.ok) {
        setToast({ type: "error", message: order.detail || "Couldn't start the payment. Please try again." });
        return;
      }
      const Razorpay = await loadRazorpay();
      const rzp = new Razorpay({
        key: order.key || process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID,
        amount: order.amount,
        currency: "INR",
        name: "Caliber Education",
        description: t.title,
        order_id: order.orderId,
        theme: { color: "#f59e0b" },
        handler: async (response: RazorpayResponse) => {
          const verify = await fetch(`${apiURL}/api/payments/verify-mcq-payment`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            }),
          });
          if (verify.ok) {
            setToast({ type: "success", message: "You're registered! You can take the test now." });
            loadStatus();
          } else {
            const err = await verify.json().catch(() => ({}));
            setToast({ type: "error", message: `Payment verification failed: ${err.detail || "please contact support"}` });
          }
        },
      });
      rzp.on("payment.failed", () => setToast({ type: "error", message: "Payment didn't go through. No amount was charged — please try again." }));
      rzp.open();
    } catch {
      setToast({ type: "error", message: "Something went wrong. Please try again." });
    } finally {
      setBusyId(null);
    }
  }

  async function submitUpi(details: UpiSubmitDetails) {
    if (!upiFor) return { success: false, message: "Something went wrong." };
    const res = await fetch(`${apiURL}/api/payments/submit-manual-scholarship`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ paperId: upiFor.id, ...details }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      loadStatus();
      return { success: true };
    }
    return { success: false, message: data.detail || "Couldn't submit your payment. Please try again." };
  }

  const overlays = (
    <>
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <UpiPaymentModal
        open={upiFor !== null}
        onClose={() => setUpiFor(null)}
        amount={upiFor?.price ?? 0}
        itemLabel={upiFor?.title ?? ""}
        onSubmit={submitUpi}
      />
    </>
  );

  return {
    tests,
    overlays,
    statusOf: (t: ScholarshipTest) => (isAuthenticated ? status[t.id] : undefined),
    isBusy: (t: ScholarshipTest) => busyId === t.id,
    registerUpi: (t: ScholarshipTest) => (isAuthenticated ? setUpiFor(t) : requireLogin()),
    registerRazorpay: payWithRazorpay,
  };
}

export type Scholarship = ReturnType<typeof useScholarship>;

// Register / Start / pending / View result, depending on where the student is.
function ScholarshipAction({ sch, t, compact = false }: { sch: Scholarship; t: ScholarshipTest; compact?: boolean }) {
  const st = sch.statusOf(t);
  const busy = sch.isBusy(t);
  const size = compact ? "px-3.5 py-2 rounded-xl text-xs" : "px-6 py-3 rounded-2xl text-sm";
  const note = `flex items-center gap-2 ${size} bg-white/70 dark:bg-white/5 border border-amber-500/30 font-bold text-ink-navy dark:text-white`;
  if (st?.attempted) {
    return st.resultsPublished ? (
      <Link href={`/scholarship/${t.id}/result`}
        className={`inline-flex items-center justify-center gap-2 ${size} bg-amber-500 hover:bg-amber-400 text-slate-950 font-black transition-colors`}>
        View your result <ArrowRight className="w-4 h-4" />
      </Link>
    ) : (
      <div className={note}><Hourglass className="w-4 h-4 text-amber-500" /> {compact ? "Result coming soon" : "Submitted · result coming soon"}</div>
    );
  }
  if (st?.registered) {
    return (
      <Link href={`/quiz/${t.id}`}
        className={`inline-flex items-center justify-center gap-2 ${size} bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-black transition-colors`}>
        <CheckCircle2 className="w-4 h-4" /> Start the test
      </Link>
    );
  }
  if (st?.paymentPending) {
    return <div className={note}><Hourglass className="w-4 h-4 text-amber-500" /> {compact ? "Verifying payment" : "Payment being verified"}</div>;
  }
  return (
    <div className={`flex ${compact ? "flex-row flex-wrap justify-end" : "flex-col"} gap-2`}>
      {(paymentMode === "manual" || paymentMode === "both") && (
        <button onClick={() => sch.registerUpi(t)}
          className={`inline-flex items-center justify-center gap-2 ${size} bg-amber-500 hover:bg-amber-400 text-slate-950 font-black transition-colors`}>
          <CreditCard className="w-4 h-4" /> {compact ? "Register" : `Register via UPI — ₹${t.price}`}
        </button>
      )}
      {(paymentMode === "razorpay" || paymentMode === "both") && (
        <button disabled={busy} onClick={() => sch.registerRazorpay(t)}
          className={`inline-flex items-center justify-center gap-2 ${size} font-black transition-colors disabled:opacity-50 ${paymentMode === "both"
            ? "border border-amber-500/50 text-ink-navy dark:text-white hover:bg-amber-500/10"
            : "bg-amber-500 hover:bg-amber-400 text-slate-950"}`}>
          <CreditCard className="w-4 h-4" /> {busy ? "Opening payment…" : compact ? (paymentMode === "both" ? "Pay online" : "Register") : `Register — ₹${t.price}`}
        </button>
      )}
    </div>
  );
}

// Banner at the top of the MCQ page.
export function ScholarshipBanner({ sch }: { sch: Scholarship }) {
  if (sch.tests.length === 0) return null;
  return (
    <section className="max-w-7xl mx-auto px-6 sm:px-8 pt-24 -mb-16 relative z-10">
      <div className="space-y-4">
        {sch.tests.map((t) => {
          const st = sch.statusOf(t);
          const showPrice = !st?.attempted && !st?.registered && !st?.paymentPending;
          return (
            <div key={t.id}
              className="relative overflow-hidden rounded-3xl border border-amber-500/40 bg-gradient-to-r from-amber-50 via-white to-amber-50 dark:from-amber-500/10 dark:via-slate-900/80 dark:to-amber-500/5 p-6 sm:p-8 shadow-xl">
              <div className="absolute -top-24 -right-24 w-72 h-72 bg-amber-400/20 blur-[90px] rounded-full pointer-events-none" />
              <div className="relative flex flex-col lg:flex-row lg:items-center justify-between gap-6">
                <div className="min-w-0">
                  <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-700 dark:text-amber-300 text-xs font-bold mb-3">
                    <Award className="w-3.5 h-3.5" /> Scholarship Test
                  </div>
                  <h2 className="text-xl sm:text-3xl font-extrabold text-ink-navy dark:text-white font-heading tracking-tight">{t.title}</h2>
                  {t.description && <p className="mt-2 text-sm text-slate-600 dark:text-slate-300/80 max-w-2xl">{t.description}</p>}
                  <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
                    <span className="flex items-center gap-1.5"><FileText className="w-4 h-4 text-amber-500" /> {t.questionCount} questions</span>
                    <span className="flex items-center gap-1.5"><Clock className="w-4 h-4 text-amber-500" /> {t.durationMinutes} minutes</span>
                    <span className="flex items-center gap-1.5"><Trophy className="w-4 h-4 text-amber-500" /> One attempt · All India rank</span>
                  </div>
                </div>
                <div className="flex flex-col items-stretch lg:items-end gap-2 shrink-0">
                  {showPrice && (
                    <div className="text-right">
                      <span className="text-3xl font-black text-ink-navy dark:text-white">₹{t.price}</span>
                      <span className="text-xs text-slate-500 dark:text-slate-400"> one-time</span>
                    </div>
                  )}
                  <ScholarshipAction sch={sch} t={t} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// Card in the level's subject grid, styled like the subject cards beside it.
export function ScholarshipCard({ sch, t, index }: { sch: Scholarship; t: ScholarshipTest; index: number }) {
  const st = sch.statusOf(t);
  const showPrice = !st?.attempted && !st?.registered && !st?.paymentPending;
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.3 }}
      className="relative bg-white dark:bg-slate-900/60 border border-amber-500/40 rounded-3xl p-6 backdrop-blur-xl flex flex-col justify-between overflow-hidden"
    >
      <div className="absolute inset-0 bg-gradient-to-br from-amber-400/15 via-transparent to-transparent rounded-3xl pointer-events-none" />
      <div className="relative">
        <div className="flex items-center justify-between gap-2 mb-4">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-amber-500/10 border border-amber-500/40 text-amber-600 dark:text-amber-400 text-xs font-black tracking-wider uppercase">
            <Award className="w-3.5 h-3.5" /> Scholarship
          </span>
          <span className="text-[11px] font-bold text-slate-500 dark:text-slate-400">One attempt</span>
        </div>
        <h3 className="text-xl font-bold text-ink-navy dark:text-white font-heading leading-snug">{t.title}</h3>
        <p className="mt-2.5 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed line-clamp-2">
          {t.description || "Compete with CA students across India and win a scholarship."}
        </p>
        <div className="mt-5 pt-4 border-t border-white/5 grid grid-cols-2 gap-3 text-xs">
          <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
            <FileText className="w-3.5 h-3.5 text-amber-500" /><span>{t.questionCount} questions</span>
          </div>
          <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
            <Clock className="w-3.5 h-3.5 text-amber-500" /><span>{t.durationMinutes} minutes</span>
          </div>
        </div>
      </div>
      <div className="relative mt-6 pt-4 border-t border-white/10 flex items-center justify-between gap-3">
        {showPrice ? (
          <div>
            <span className="text-[11px] text-slate-500 block uppercase font-medium">One-time fee</span>
            <span className="text-xl font-extrabold text-ink-navy dark:text-white">₹{t.price}</span>
          </div>
        ) : (
          <span className="text-[11px] font-bold text-amber-600 dark:text-amber-400 uppercase tracking-wide">
            {st?.attempted ? "Submitted" : st?.registered ? "Registered" : "Payment sent"}
          </span>
        )}
        <ScholarshipAction sch={sch} t={t} compact />
      </div>
    </motion.div>
  );
}
