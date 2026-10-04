"use client";

import { useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import Image from "next/image";
import { motion, AnimatePresence } from "framer-motion";
import { X, Copy, Check, ChevronDown, ShieldCheck, CheckCircle2, Loader2 } from "lucide-react";

// The QR image is a real, static UPI QR (HDFC) — it can't encode a dynamic
// amount like a generated collect-request QR could, so the exact amount is
// shown as text next to it instead. If this VPA/QR image ever changes,
// update both together — they must stay in sync.
const UPI_VPA = "8653065093@hdfc";

export interface UpiSubmitDetails {
  upiReference: string;
  payerUpiId: string;
  payerName: string;
}

interface UpiPaymentModalProps {
  open: boolean;
  onClose: () => void;
  amount: number;
  itemLabel: string;
  onSubmit: (details: UpiSubmitDetails) => Promise<{ success: boolean; message?: string }>;
}

export function UpiPaymentModal({ open, onClose, amount, itemLabel, onSubmit }: UpiPaymentModalProps) {
  const [reference, setReference] = useState("");
  const [payerUpiId, setPayerUpiId] = useState("");
  const [payerName, setPayerName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showHint, setShowHint] = useState(false);

  const handleClose = () => {
    // Reset for next time this modal opens, but only once fully closed.
    onClose();
    setTimeout(() => {
      setReference("");
      setPayerUpiId("");
      setPayerName("");
      setError("");
      setSubmitted(false);
      setShowHint(false);
    }, 200);
  };

  const handleCopyVpa = async () => {
    try {
      await navigator.clipboard.writeText(UPI_VPA);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable — copy button just won't confirm, no crash */ }
  };

  const handleSubmit = async () => {
    const trimmedRef = reference.trim();
    const trimmedUpiId = payerUpiId.trim();
    const trimmedName = payerName.trim();
    if (!trimmedRef) {
      setError("Please enter your UPI transaction reference.");
      return;
    }
    if (!trimmedUpiId || !trimmedName) {
      setError("Please enter the UPI ID and name you paid from.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const result = await onSubmit({ upiReference: trimmedRef, payerUpiId: trimmedUpiId, payerName: trimmedName });
      if (result.success) {
        setSubmitted(true);
      } else {
        setError(result.message || "Couldn't submit your payment. Please try again.");
      }
    } catch {
      setError("Error contacting the server. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  // Rendered into <body> so no parent's stacking context (e.g. a "relative
  // z-10" section) can trap it under the sticky level bar or navbar.
  const isClient = useSyncExternalStore(subscribeNoop, () => true, () => false);
  if (!isClient) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4 sm:p-6">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-ink-navy/60 backdrop-blur-sm"
            onClick={handleClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 12 }}
            className="relative w-full max-w-md max-h-[90vh] overflow-y-auto bg-white dark:bg-line-gray-dark rounded-2xl shadow-2xl border border-line-gray-light dark:border-line-gray-dark"
          >
            <button
              onClick={handleClose}
              aria-label="Close"
              className="absolute top-4 right-4 p-1.5 rounded-lg text-slate dark:text-paper/60 hover:bg-line-gray-light dark:hover:bg-line-gray-dark/60 transition-colors z-10"
            >
              <X className="w-4 h-4" />
            </button>

            {submitted ? (
              <div className="p-8 text-center space-y-4">
                <div className="w-14 h-14 rounded-full bg-signal-emerald/10 flex items-center justify-center mx-auto">
                  <CheckCircle2 className="w-7 h-7 text-signal-emerald" />
                </div>
                <h2 className="text-xl font-bold font-heading text-ink-navy dark:text-paper">Submitted for review</h2>
                <p className="text-sm text-slate dark:text-paper/60 leading-relaxed">
                  We've received your payment reference for <span className="font-semibold text-ink-navy dark:text-paper">{itemLabel}</span>.
                  Our team verifies manually and usually confirms within a few hours — you'll get access as soon as it's approved,
                  and we've sent a confirmation to your email.
                </p>
                <button
                  onClick={handleClose}
                  className="w-full py-3 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all text-sm"
                >
                  Done
                </button>
              </div>
            ) : (
              <div className="p-6 sm:p-7 space-y-5">
                <div className="space-y-1 pr-6">
                  <h2 className="text-lg font-bold font-heading text-ink-navy dark:text-paper">Pay via UPI</h2>
                  <p className="text-xs text-slate dark:text-paper/60">{itemLabel}</p>
                </div>

                <div className="flex flex-col items-center gap-3 p-5 rounded-xl bg-line-gray-light/40 dark:bg-ink-navy/40 border border-line-gray-light dark:border-line-gray-dark">
                  <div className="relative w-44 h-44 rounded-lg overflow-hidden bg-white">
                    <Image src="/Payment.jpeg" alt="UPI payment QR code" fill className="object-contain" sizes="176px" />
                  </div>
                  <button
                    onClick={handleCopyVpa}
                    className="flex items-center gap-1.5 text-xs font-mono text-ink-navy dark:text-paper bg-white dark:bg-line-gray-dark/60 border border-line-gray-light dark:border-line-gray-dark rounded-lg px-3 py-1.5 hover:border-signal-emerald/40 transition-colors"
                  >
                    {UPI_VPA}
                    {copied ? <Check className="w-3.5 h-3.5 text-signal-emerald" /> : <Copy className="w-3.5 h-3.5 opacity-60" />}
                  </button>
                  <p className="text-sm text-center">
                    <span className="text-slate dark:text-paper/60">Pay exactly </span>
                    <span className="font-heading font-extrabold text-lg text-ink-navy dark:text-paper">₹{amount.toLocaleString()}</span>
                    <span className="text-slate dark:text-paper/60"> to this UPI ID</span>
                  </p>
                </div>

                <div className="flex items-start gap-2 text-[11px] text-slate dark:text-paper/50 leading-relaxed">
                  <ShieldCheck className="w-3.5 h-3.5 text-signal-emerald flex-shrink-0 mt-0.5" />
                  <span>Reviewed manually by our team, usually within a few hours. We never ask for your card, bank password, or OTP — only the public transaction reference below.</span>
                </div>

                <div className="space-y-2 pt-1 border-t border-line-gray-light dark:border-line-gray-dark">
                  <label className="text-xs font-bold text-ink-navy dark:text-paper block pt-4">
                    Already paid? Tell us where it came from
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <label className="text-[10px] font-semibold text-slate dark:text-paper/50">Your UPI ID</label>
                      <input
                        type="text"
                        value={payerUpiId}
                        onChange={(e) => setPayerUpiId(e.target.value)}
                        placeholder="e.g. name@oksbi"
                        className="w-full px-3 py-2.5 text-sm font-mono border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/30 text-ink-navy dark:text-paper rounded-lg focus:outline-none focus:border-signal-emerald transition-colors"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] font-semibold text-slate dark:text-paper/50">Name on that UPI account</label>
                      <input
                        type="text"
                        value={payerName}
                        onChange={(e) => setPayerName(e.target.value)}
                        placeholder="e.g. Rahul Sharma"
                        className="w-full px-3 py-2.5 text-sm border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/30 text-ink-navy dark:text-paper rounded-lg focus:outline-none focus:border-signal-emerald transition-colors"
                      />
                    </div>
                  </div>
                  <label className="text-xs font-bold text-ink-navy dark:text-paper block pt-2">
                    UPI transaction reference
                  </label>
                  <input
                    type="text"
                    value={reference}
                    onChange={(e) => setReference(e.target.value)}
                    placeholder="e.g. 123456789012"
                    className="w-full px-3 py-2.5 text-sm font-mono border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/30 text-ink-navy dark:text-paper rounded-lg focus:outline-none focus:border-signal-emerald transition-colors"
                    onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                  />

                  <button
                    type="button"
                    onClick={() => setShowHint((v) => !v)}
                    className="flex items-center gap-1 text-[11px] font-semibold text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper transition-colors"
                  >
                    <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showHint ? "rotate-180" : ""}`} />
                    Where do I find this?
                  </button>
                  <AnimatePresence>
                    {showHint && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        className="overflow-hidden"
                      >
                        <div className="text-[11px] text-slate dark:text-paper/60 leading-relaxed bg-line-gray-light/40 dark:bg-ink-navy/40 rounded-lg p-3 space-y-2">
                          <p>
                            After paying, open your UPI app → go to your transaction/payment history → tap this specific payment → look for
                            {" "}<strong className="text-ink-navy dark:text-paper">"UTR Number"</strong>, <strong className="text-ink-navy dark:text-paper">"Reference ID"</strong>, or{" "}
                            <strong className="text-ink-navy dark:text-paper">"Transaction ID"</strong> (usually under "transaction details"). It's typically 12 digits.
                          </p>
                          <ul className="space-y-1 pl-3 list-disc marker:text-slate/40">
                            <li><strong className="text-ink-navy dark:text-paper">Google Pay:</strong> History → tap the payment → "UPI transaction ID"</li>
                            <li><strong className="text-ink-navy dark:text-paper">PhonePe:</strong> History → tap the payment → "Transaction ID"</li>
                            <li><strong className="text-ink-navy dark:text-paper">Paytm:</strong> Balance &amp; History → tap the payment → "UTR No."</li>
                          </ul>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {error && <p className="text-xs font-semibold text-alert-coral">{error}</p>}
                </div>

                <button
                  onClick={handleSubmit}
                  disabled={submitting || !reference.trim() || !payerUpiId.trim() || !payerName.trim()}
                  className="w-full py-3 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy font-bold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {submitting ? "Submitting…" : "Submit for Verification"}
                </button>
              </div>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

const subscribeNoop = () => () => {};
