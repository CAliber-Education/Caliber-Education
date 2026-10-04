"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
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

// All India Scholarship Test card(s) at the top of the MCQ page: register
// (pay once), take it once, then wait for results to be published.
export default function ScholarshipSection() {
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

  if (tests.length === 0) return null;

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

  return (
    <section className="max-w-7xl mx-auto px-6 sm:px-8 pt-24 -mb-16 relative z-10">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <UpiPaymentModal
        open={upiFor !== null}
        onClose={() => setUpiFor(null)}
        amount={upiFor?.price ?? 0}
        itemLabel={upiFor?.title ?? ""}
        onSubmit={submitUpi}
      />
      <div className="space-y-4">
        {tests.map((t) => {
          const st = isAuthenticated ? status[t.id] : undefined;
          const busy = busyId === t.id;
          return (
            <div
              key={t.id}
              className="relative overflow-hidden rounded-3xl border border-amber-500/40 bg-gradient-to-r from-amber-50 via-white to-amber-50 dark:from-amber-500/10 dark:via-slate-900/80 dark:to-amber-500/5 p-6 sm:p-8 shadow-xl"
            >
              <div className="absolute -top-24 -right-24 w-72 h-72 bg-amber-400/20 blur-[90px] rounded-full pointer-events-none" />
              <div className="relative flex flex-col lg:flex-row lg:items-center justify-between gap-6">
                <div className="min-w-0">
                  <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-700 dark:text-amber-300 text-xs font-bold mb-3">
                    <Award className="w-3.5 h-3.5" /> Scholarship Test
                  </div>
                  <h2 className="text-xl sm:text-3xl font-extrabold text-ink-navy dark:text-white font-heading tracking-tight">{t.title}</h2>
                  {t.description && (
                    <p className="mt-2 text-sm text-slate-600 dark:text-slate-300/80 max-w-2xl">{t.description}</p>
                  )}
                  <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
                    <span className="flex items-center gap-1.5"><FileText className="w-4 h-4 text-amber-500" /> {t.questionCount} questions</span>
                    <span className="flex items-center gap-1.5"><Clock className="w-4 h-4 text-amber-500" /> {t.durationMinutes} minutes</span>
                    <span className="flex items-center gap-1.5"><Trophy className="w-4 h-4 text-amber-500" /> One attempt · All India rank</span>
                  </div>
                </div>

                <div className="flex flex-col items-stretch lg:items-end gap-2 shrink-0">
                  {st?.attempted ? (
                    st.resultsPublished ? (
                      <Link href={`/scholarship/${t.id}/result`}
                        className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-2xl bg-amber-500 hover:bg-amber-400 text-slate-950 text-sm font-black transition-colors">
                        View your result <ArrowRight className="w-4 h-4" />
                      </Link>
                    ) : (
                      <div className="flex items-center gap-2 px-5 py-3 rounded-2xl bg-white/70 dark:bg-white/5 border border-amber-500/30 text-sm font-bold text-ink-navy dark:text-white">
                        <Hourglass className="w-4 h-4 text-amber-500" /> Submitted · result coming soon
                      </div>
                    )
                  ) : st?.registered ? (
                    <Link href={`/quiz/${t.id}`}
                      className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-2xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-sm font-black transition-colors">
                      <CheckCircle2 className="w-4 h-4" /> Start the test
                    </Link>
                  ) : st?.paymentPending ? (
                    <div className="flex items-center gap-2 px-5 py-3 rounded-2xl bg-white/70 dark:bg-white/5 border border-amber-500/30 text-sm font-bold text-ink-navy dark:text-white">
                      <Hourglass className="w-4 h-4 text-amber-500" /> Payment being verified
                    </div>
                  ) : (
                    <>
                      <div className="text-right">
                        <span className="text-3xl font-black text-ink-navy dark:text-white">₹{t.price}</span>
                        <span className="text-xs text-slate-500 dark:text-slate-400"> one-time</span>
                      </div>
                      {(paymentMode === "manual" || paymentMode === "both") && (
                        <button
                          onClick={() => (isAuthenticated ? setUpiFor(t) : requireLogin())}
                          className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-2xl bg-amber-500 hover:bg-amber-400 text-slate-950 text-sm font-black transition-colors"
                        >
                          <CreditCard className="w-4 h-4" /> Register via UPI — ₹{t.price}
                        </button>
                      )}
                      {(paymentMode === "razorpay" || paymentMode === "both") && (
                        <button
                          disabled={busy}
                          onClick={() => payWithRazorpay(t)}
                          className={`inline-flex items-center justify-center gap-2 px-6 py-3 rounded-2xl text-sm font-black transition-colors disabled:opacity-50 ${paymentMode === "both"
                            ? "border border-amber-500/50 text-ink-navy dark:text-white hover:bg-amber-500/10"
                            : "bg-amber-500 hover:bg-amber-400 text-slate-950"}`}
                        >
                          <CreditCard className="w-4 h-4" /> {busy ? "Opening payment…" : `Register — ₹${t.price}`}
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
