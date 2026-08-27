"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "@/context/AuthContext";
import { Toast, type ToastState } from "@/components/Toast";
import { UpiPaymentModal, type UpiSubmitDetails } from "@/components/UpiPaymentModal";
import {
  Search,
  Zap,
  Sparkles,
  ShieldCheck,
  Clock,
  ArrowRight,
  X,
  Tag,
  Check,
  Flame,
  Layers,
  Star,
  Percent,
  BookOpen,
  ChevronRight,
  TrendingUp,
  AlertCircle,
  CreditCard,
  RefreshCw,
} from "lucide-react";
import {
  MCQLevel,
  PricingDuration,
  MCQSubject,
  MCQBundle,
  INITIAL_MCQ_SUBJECTS,
  INITIAL_MCQ_BUNDLES,
  DURATION_LABELS,
  calculateMCQCartPrice,
} from "@/lib/mcqPricingData";

export default function MCQClient({
  initialSubjects,
  initialBundles,
}: {
  initialSubjects: MCQSubject[];
  initialBundles: MCQBundle[];
}) {
  const router = useRouter();
  const { isAuthenticated } = useAuth();
  const [activeLevel, setActiveLevel] = useState<MCQLevel>("FINAL");
  const [searchQuery, setSearchQuery] = useState("");
  // Fetched server-side (see mcq/page.tsx) so the catalog is present in the
  // initial HTML for SEO, falling back to the seeded matrix if the server
  // fetch came back empty (backend briefly unreachable, etc.).
  const [allSubjects] = useState<MCQSubject[]>(initialSubjects.length > 0 ? initialSubjects : INITIAL_MCQ_SUBJECTS);
  const [allBundles] = useState<MCQBundle[]>(initialBundles.length > 0 ? initialBundles : INITIAL_MCQ_BUNDLES);
  const [ownedMcqSubjects, setOwnedMcqSubjects] = useState<string[]>([]);

  useEffect(() => {
    const fetchOwned = async () => {
      try {
        const token = localStorage.getItem("caliber_jwt");
        if (!token) return;
        const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
        const res = await fetch(`${apiURL}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          setOwnedMcqSubjects(data.mcqPurchases || []);
        }
      } catch (e) {
        console.warn(e);
      }
    };
    fetchOwned();
  }, []);

  // Selected Modal / Drawer State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isExtendMode, setIsExtendMode] = useState(false);
  const [modalSelectedSubjectIds, setModalSelectedSubjectIds] = useState<string[]>([]);
  const [selectedDuration, setSelectedDuration] = useState<PricingDuration>("1_month");
  const [couponCode, setCouponCode] = useState("");
  const [couponApplied, setCouponApplied] = useState(false);
  const [couponDiscount, setCouponDiscount] = useState(0);
  const [couponError, setCouponError] = useState("");
  const [couponLoading, setCouponLoading] = useState(false);

  // Payment Processing State
  const [isProcessing, setIsProcessing] = useState(false);
  const [activePaymentMethod, setActivePaymentMethod] = useState<"razorpay" | "manual">("razorpay");
  const [purchaseSuccess, setPurchaseSuccess] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [purchasedInfo, setPurchasedInfo] = useState<{ title: string; amount: number } | null>(null);
  const [showUpiModal, setShowUpiModal] = useState(false);
  const paymentMode = process.env.NEXT_PUBLIC_PAYMENT_MODE || "manual";

  // Filter subjects for the active level
  const levelSubjects = useMemo(() => {
    return allSubjects.filter((s) => s.level === activeLevel);
  }, [allSubjects, activeLevel]);

  // Filter subjects for display (flat catalog)
  const filteredSubjects = useMemo(() => {
    return levelSubjects.filter((subject) =>
      subject.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      subject.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
      subject.description.toLowerCase().includes(searchQuery.toLowerCase())
    );
  }, [levelSubjects, searchQuery]);

  // Open checkout modal — if subject is already owned, open in "extend" mode
  const handleOpenSubjectModal = (subject: MCQSubject, extend = false) => {
    setModalSelectedSubjectIds([subject.id]);
    setIsExtendMode(extend);
    setSelectedDuration("1_month");
    setCouponCode("");
    setCouponApplied(false);
    setCouponDiscount(0);
    setCouponError("");
    setPurchaseSuccess(false);
    setIsModalOpen(true);
  };

  // Open modal directly with a bundle
  const handleOpenBundleModal = (bundle: MCQBundle) => {
    const subIds = bundle.subjectIds || (bundle as any).subject_ids || [];
    setModalSelectedSubjectIds(subIds);
    setSelectedDuration("1_month");
    setCouponCode("");
    setCouponApplied(false);
    setCouponDiscount(0);
    setCouponError("");
    setPurchaseSuccess(false);
    setIsModalOpen(true);
  };

  // Calculate live dynamic pricing & smart upsell for current modal state
  const cartCalculation = useMemo(() => {
    return calculateMCQCartPrice(
      activeLevel,
      modalSelectedSubjectIds,
      selectedDuration,
      allSubjects,
      allBundles
    );
  }, [activeLevel, modalSelectedSubjectIds, selectedDuration, allSubjects, allBundles]);

  // Apply smart upsell recommendation
  const handleApplyUpsell = (subjectIds: string[]) => {
    setModalSelectedSubjectIds(subjectIds);
  };

  // Toggle subject inside modal
  const handleToggleSubject = (id: string) => {
    if (modalSelectedSubjectIds.includes(id)) {
      if (modalSelectedSubjectIds.length > 1) {
        setModalSelectedSubjectIds(modalSelectedSubjectIds.filter((sId) => sId !== id));
      }
    } else {
      setModalSelectedSubjectIds([...modalSelectedSubjectIds, id]);
    }
  };

  // Apply coupon code
  const handleApplyCoupon = async () => {
    const code = couponCode.trim().toUpperCase();
    if (!code) return;

    setCouponLoading(true);
    setCouponError("");
    setCouponApplied(false);

    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";
      const res = await fetch(`${apiURL}/api/coupons/validate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          code: code,
          cart_amount: cartCalculation.discountedPrice
        })
      });
      const data = await res.json();
      if (data.valid) {
        setCouponDiscount(data.discount_amount || 0);
        setCouponApplied(true);
        setCouponError("");
      } else {
        setCouponError(data.message || "Invalid or expired coupon code");
        setCouponApplied(false);
        setCouponDiscount(0);
      }
    } catch (e) {
      setCouponError("Network error validating coupon");
    } finally {
      setCouponLoading(false);
    }
  };

  // Final Payable Price
  const finalPayablePrice = Math.max(0, cartCalculation.discountedPrice - couponDiscount);

  // Handle Checkout / Razorpay Integration
  const handleCheckout = async () => {
    if (!isAuthenticated) {
      router.push("/login?next=/mcq");
      return;
    }
    setIsProcessing(true);
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("caliber_jwt") : null;
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";

      // Create backend order
      const orderRes = await fetch(`${apiURL}/api/payments/create-mcq-order`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token ? `Bearer ${token}` : "",
        },
        body: JSON.stringify({
          level: activeLevel,
          subjectIds: modalSelectedSubjectIds,
          duration: selectedDuration,
          couponCode: couponApplied ? couponCode : undefined,
        }),
      });

      if (orderRes.ok) {
        const orderData = await orderRes.json();

        // Check which payment method is selected
        if (activePaymentMethod === "razorpay") {
          // REAL RAZORPAY PAYMENT

          // Dynamically load Razorpay script if not already loaded
          if (!(window as any).Razorpay) {
            await new Promise<void>((resolve, reject) => {
              const script = document.createElement("script");
              script.src = "https://checkout.razorpay.com/v1/checkout.js";
              script.onload = () => {
                resolve();
              };
              script.onerror = () => reject(new Error("Failed to load Razorpay SDK"));
              document.body.appendChild(script);
            });
          }

          const rzp = new (window as any).Razorpay({
            key: orderData.key || process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID,
            // Server-computed amount from the order the backend already
            // created — matches the other 3 purchase flows. Razorpay
            // resolves the actual chargeable amount from order_id
            // regardless, but this avoids ever displaying a different
            // number than what create-mcq-order priced (e.g. if client-side
            // coupon math ever drifts from the server's own calculation).
            amount: orderData.amount,
            currency: "INR",
            name: "Caliber Education",
            description: `${activeLevel} MCQ - ${DURATION_LABELS[selectedDuration].label}`,
            order_id: orderData.orderId,
            handler: async (response: any) => {
              setIsProcessing(true);
              
              // Verify payment on backend
              const verifyRes = await fetch(`${apiURL}/api/payments/verify-mcq-payment`, {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({
                  razorpay_order_id: response.razorpay_order_id,
                  razorpay_payment_id: response.razorpay_payment_id,
                  razorpay_signature: response.razorpay_signature,
                }),
              });
              
              if (verifyRes.ok) {
                setPurchasedInfo({
                  title: `${activeLevel} MCQ Package (${DURATION_LABELS[selectedDuration].label})`,
                  amount: finalPayablePrice,
                });
                setPurchaseSuccess(true);
                setIsProcessing(false);
                
                // Redirect to dashboard after 2 seconds
                setTimeout(() => {
                  window.location.href = "/dashboard?tab=mcqs";
                }, 2000);
              } else {
                const errData = await verifyRes.json().catch(() => ({}));
                setToast({ type: "error", message: `Payment verification failed: ${errData.detail || "Please try again"}` });
                setIsProcessing(false);
              }
            },
            prefill: {
              email: token ? (() => {
                try {
                  return JSON.parse(atob(token.split('.')[1])).email;
                } catch {
                  return "";
                }
              })() : "",
            },
            theme: { color: "#10b981" },
            modal: {
              ondismiss: () => {
                setIsProcessing(false);
              }
            }
          });

          rzp.on("payment.failed", () => {
            setToast({ type: "error", message: "Payment didn't go through. No amount was charged — please try again." });
            setIsProcessing(false);
          });

          rzp.open();
          setIsProcessing(false); // Allow user to interact while modal is open
          
        } else {
          // TEST MODE - Instant activation without Razorpay
          const confirmRes = await fetch(`${apiURL}/api/payments/mock-confirm-mcq`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: token ? `Bearer ${token}` : "",
            },
            body: JSON.stringify({
              razorpay_order_id: orderData.orderId,
              razorpay_payment_id: "pay_TEST_" + Math.random().toString(36).substring(7),
              razorpay_signature: "test_mode_signature"
            }),
          });

          if (confirmRes.ok) {
            setPurchasedInfo({
              title: `${activeLevel} MCQ Package (${DURATION_LABELS[selectedDuration].label})`,
              amount: finalPayablePrice,
            });
            setPurchaseSuccess(true);
            setIsProcessing(false);

            // Auto-redirect to dashboard after 2 seconds
            setTimeout(() => {
              window.location.href = "/dashboard?tab=mcqs";
            }, 2000);
          } else {
            const errorData = await confirmRes.json().catch(() => ({}));
            console.error("[MCQ] Test payment failed:", confirmRes.status, errorData);
            setToast({ type: "error", message: `Test payment confirmation failed: ${errorData.detail || "Please check backend logs"}` });
            setIsProcessing(false);
          }
        }
      } else {
        // orderRes not ok — show real error
        const errData = await orderRes.json().catch(() => ({}));
        setToast({ type: "error", message: `Payment setup failed: ${errData.detail || "Please try again."}` });
        setIsProcessing(false);
        return;
      }
    } catch (error) {
      console.error("Payment error", error);
      setToast({ type: "error", message: "Something went wrong. Please try again." });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleUpiSubmit = async (details: UpiSubmitDetails) => {
    const token = typeof window !== "undefined" ? localStorage.getItem("caliber_jwt") : null;
    const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
    const res = await fetch(`${apiURL}/api/payments/submit-manual-mcq`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: token ? `Bearer ${token}` : "" },
      body: JSON.stringify({
        level: activeLevel,
        subjectIds: modalSelectedSubjectIds,
        duration: selectedDuration,
        couponCode: couponApplied ? couponCode : undefined,
        ...details,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) return { success: true };
    return { success: false, message: data.detail || "Couldn't submit your payment. Please try again." };
  };

  const levelBadges: Record<MCQLevel, { label: string; tag: string; bg: string; border: string; text: string }> = {
    FINAL: {
      label: "CA Final",
      tag: "Advanced Standards & Case Studies",
      bg: "from-blue-500/20 via-indigo-500/10 to-transparent",
      border: "border-blue-500/30",
      text: "text-blue-400",
    },
    INTERMEDIATE: {
      label: "CA Intermediate",
      tag: "Conceptual Clarity & Practice Drills",
      bg: "from-emerald-500/20 via-teal-500/10 to-transparent",
      border: "border-emerald-500/30",
      text: "text-emerald-400",
    },
    FOUNDATION: {
      label: "CA Foundation",
      tag: "Speed, Accuracy & Fundamentals",
      bg: "from-purple-500/20 via-pink-500/10 to-transparent",
      border: "border-purple-500/30",
      text: "text-purple-400",
    },
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 selection:bg-emerald-500 selection:text-black">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <UpiPaymentModal
        open={showUpiModal}
        onClose={() => setShowUpiModal(false)}
        amount={finalPayablePrice}
        itemLabel={`${activeLevel} MCQ Package (${DURATION_LABELS[selectedDuration].label})`}
        onSubmit={handleUpiSubmit}
      />
      {/* ─── Top High-Value Bundle Recommendation Header ─── */}
      <section className="relative pt-24 pb-8 overflow-hidden">
        {/* Ambient Gradient Glows */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[350px] bg-gradient-to-tr from-emerald-500/15 via-cyan-500/15 to-purple-500/10 blur-[130px] rounded-full pointer-events-none -z-10" />

        <div className="max-w-7xl mx-auto px-6 sm:px-8">
          <div className="relative rounded-3xl p-8 sm:p-10 bg-gradient-to-r from-white/90 dark:from-slate-900/90 via-white/70 dark:via-slate-900/70 to-white/90 dark:to-slate-900/90 border border-white/10 backdrop-blur-2xl overflow-hidden shadow-2xl">
            <div className="absolute top-0 right-0 w-96 h-96 bg-emerald-500/10 blur-[100px] rounded-full pointer-events-none" />

            <div className="flex flex-col lg:flex-row items-center justify-between gap-8 relative z-10">
              <div className="max-w-xl">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-bold mb-3">
                  <Flame className="w-3.5 h-3.5 text-amber-400" /> High-Value Bundles
                </div>
                <h1 className="text-2xl sm:text-4xl font-extrabold text-ink-navy dark:text-white font-heading tracking-tight leading-tight">
                  Preparing for all subjects in {levelBadges[activeLevel].label}?
                </h1>
                <p className="mt-3 text-sm text-slate-600 dark:text-slate-300/80 leading-relaxed">
                  Save up to 40% with pre-configured group packages and super bundles. Get complete
                  access to all test series, case scenario simulators, and leaderboard rankings.
                </p>
              </div>

              {/* Bundle Cards Quick List */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 w-full lg:max-w-2xl">
                {allBundles
                  .filter((b) => (b.level || "FINAL").toUpperCase() === activeLevel)
                  .map((b, idx, arr) => {
                    const subCount = b.subjectIds?.length ?? (b as any).subject_ids?.length ?? 0;
                    const price1M = b.prices?.["1_month"] ?? 0;
                    const isSuper =
                      (b.groupName || "").toLowerCase().includes("both") ||
                      (b.badge || "").toLowerCase().includes("super") ||
                      (arr.length % 2 !== 0 && idx === arr.length - 1);

                    return (
                      <div
                        key={b.id}
                        onClick={() => handleOpenBundleModal(b)}
                        className={`p-5 rounded-2xl bg-slate-100 dark:bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:bg-white/10 border border-white/10 hover:border-emerald-500/40 transition-all cursor-pointer group hover:scale-[1.01] shadow-lg ${isSuper && arr.length > 2 ? "sm:col-span-2" : ""
                          }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-black uppercase tracking-wider text-emerald-400">
                            {b.badge || b.groupName}
                          </span>
                          <span className="text-xs text-slate-500 dark:text-slate-400">{subCount} Subjects</span>
                        </div>
                        <h4 className="text-sm font-bold text-ink-navy dark:text-white group-hover:text-emerald-300 transition-colors">
                          {b.title}
                        </h4>
                        <div className="mt-3 flex items-baseline justify-between">
                          <div className="flex items-baseline gap-1">
                            <span className="text-lg font-black text-ink-navy dark:text-white">₹{price1M}</span>
                            <span className="text-[11px] text-slate-500 dark:text-slate-400">/ 1 Month</span>
                          </div>
                          <span className="text-xs text-emerald-400 font-bold flex items-center gap-1">
                            View Bundle <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
                          </span>
                        </div>
                      </div>
                    );
                  })}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Level Navigation & Controls Bar ─── */}
      <section className="sticky top-16 z-30 bg-slate-50 dark:bg-slate-950/85 backdrop-blur-xl border-b border-white/10 shadow-2xl">
        <div className="max-w-7xl mx-auto px-6 sm:px-8 py-4 flex flex-col md:flex-row items-center justify-between gap-4">
          {/* Level Tabs */}
          <div className="flex items-center p-1.5 bg-white/90 dark:bg-slate-900/90 border border-white/10 rounded-2xl w-full md:w-auto shadow-inner">
            {(["FINAL", "INTERMEDIATE", "FOUNDATION"] as MCQLevel[]).map((level) => {
              const isActive = activeLevel === level;
              return (
                <button
                  key={level}
                  onClick={() => setActiveLevel(level)}
                  className={`relative flex-1 md:flex-initial px-5 py-2.5 rounded-xl text-xs sm:text-sm font-bold tracking-wide transition-all duration-300 ${isActive ? "text-slate-950" : "text-slate-500 dark:text-slate-400 hover:text-ink-navy dark:text-white"
                    }`}
                >
                  {isActive && (
                    <motion.div
                      layoutId="activeLevelTab"
                      className="absolute inset-0 bg-gradient-to-r from-emerald-400 to-teal-300 rounded-xl shadow-lg shadow-emerald-500/20"
                      transition={{ type: "spring", stiffness: 450, damping: 35 }}
                    />
                  )}
                  <span className="relative z-10">{levelBadges[level].label}</span>
                </button>
              );
            })}
          </div>

          {/* Search & Quick Group Filters */}
          <div className="flex items-center gap-3 w-full md:w-auto justify-end">
            {/* Search Input */}
            <div className="relative flex-1 md:w-72">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 dark:text-slate-400" />
              <input
                type="text"
                placeholder="Search subject or code (e.g. FR, DT)..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 text-xs sm:text-sm bg-white/70 dark:bg-slate-900/70 border border-white/10 rounded-xl text-ink-navy dark:text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/40 transition-all"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-ink-navy dark:text-white"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* ─── Main Catalog: Flat Subject Listing (Glassmorphism Cards) ─── */}
      <section className="py-12 max-w-7xl mx-auto px-6 sm:px-8">
        {/* Section Header */}
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8 pb-4 border-b border-white/5">
          <div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-bold uppercase tracking-wider ${levelBadges[activeLevel].text}`}>
                {levelBadges[activeLevel].label} Catalog
              </span>
              <span className="text-slate-600">•</span>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {filteredSubjects.length} {filteredSubjects.length === 1 ? "Subject" : "Subjects"} Available
              </span>
            </div>
            <h2 className="text-2xl sm:text-3xl font-bold text-ink-navy dark:text-white tracking-tight mt-1">
              Select a Subject to Customize Your Package
            </h2>
          </div>

          {/* Quick Bundle Shortcut */}
          <div className="flex items-center gap-2">
            {allBundles
              .filter((b) => b.level === activeLevel && b.groupName === "Both Groups")
              .map((superBundle) => (
                <button
                  key={superBundle.id}
                  onClick={() => handleOpenBundleModal(superBundle)}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-amber-500/20 to-orange-500/20 border border-amber-500/40 text-amber-300 text-xs font-semibold hover:border-amber-400 hover:scale-[1.02] transition-all shadow-lg shadow-amber-500/5"
                >
                  <Flame className="w-4 h-4 text-amber-400 animate-bounce" />
                  <span>Get All 6 Subjects Super Bundle (Save Big!)</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              ))}
          </div>
        </div>

        {/* Empty State */}
        {filteredSubjects.length === 0 ? (
          <div className="text-center py-24 bg-slate-100/50 dark:bg-slate-900/30 border border-white/5 rounded-3xl backdrop-blur-xl">
            <BookOpen className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-lg font-bold text-ink-navy dark:text-white">No subjects found</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">
              No subjects matched &quot;{searchQuery}&quot;. Clear your search query and try again.
            </p>
            <button
              onClick={() => setSearchQuery("")}
              className="mt-4 px-4 py-2 bg-black/10 dark:bg-white/10 hover:bg-white/20 text-xs font-bold rounded-xl transition-all"
            >
              Reset Filters
            </button>
          </div>
        ) : (
          /* Flat Subject Grid */
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredSubjects.map((subject, idx) => {
              const startingPrice = subject.prices["1_month"] || 99;
              const isOwned = ownedMcqSubjects.includes(subject.id) || ownedMcqSubjects.includes(subject.code);

              return (
                <motion.div
                  key={subject.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.05, duration: 0.3 }}
                  onClick={() => !isOwned && handleOpenSubjectModal(subject)}
                  className={`group relative bg-white dark:bg-slate-900/60 border rounded-3xl p-6 backdrop-blur-xl transition-all duration-300 flex flex-col justify-between ${isOwned
                      ? "border-signal-emerald/40 bg-signal-emerald/5 dark:bg-signal-emerald/5 cursor-default"
                      : "hover:bg-white/90 dark:bg-slate-900/90 border-white/10 hover:border-emerald-500/40 hover:shadow-2xl hover:shadow-emerald-500/10 hover:-translate-y-1 cursor-pointer"
                    }`}
                >
                  {/* Glowing background card gradient */}
                  <div
                    className={`absolute inset-0 bg-gradient-to-br ${subject.accentGradient || "from-emerald-500/10 via-transparent to-transparent"
                      } rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none`}
                  />

                  {/* Top Bar: Code Pill & Group Tag */}
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-4">
                      <div className="flex items-center gap-2">
                        <span className="px-3 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-black tracking-wider uppercase">
                          {subject.code}
                        </span>
                        {subject.groupName !== "All" && (
                          <span className="px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-black/5 dark:bg-white/5 border border-white/10 text-slate-500 dark:text-slate-400 text-[11px] font-semibold">
                            {subject.groupName}
                          </span>
                        )}
                      </div>

                      {subject.isPopular && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-300 text-[11px] font-bold">
                          <Star className="w-3 h-3 fill-amber-400 text-amber-400" /> Popular
                        </span>
                      )}
                    </div>

                    {/* Subject Title */}
                    <h3 className="text-xl font-bold text-ink-navy dark:text-white group-hover:text-emerald-300 transition-colors font-heading leading-snug">
                      {subject.name}
                    </h3>

                    {/* Description */}
                    <p className="mt-2.5 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed line-clamp-2">
                      {subject.description}
                    </p>

                    {/* Practice Highlights */}
                    <div className="mt-5 pt-4 border-t border-white/5 grid grid-cols-2 gap-3 text-xs">
                      <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                        <Layers className="w-3.5 h-3.5 text-emerald-400" />
                        <span>{subject.testCount || 15}+ Chapter Sets</span>
                      </div>
                      <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
                        <Zap className="w-3.5 h-3.5 text-cyan-400" />
                        <span>{subject.questionCount || 450}+ Total MCQs</span>
                      </div>
                    </div>
                  </div>

                  {/* Bottom Bar: Pricing Preview & Action */}
                  <div className="mt-6 pt-4 border-t border-white/10 flex items-center justify-between">
                    <div>
                      {isOwned ? (
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-signal-emerald uppercase tracking-wide">
                          <Check className="w-3 h-3" /> Active Access
                        </span>
                      ) : (
                        <>
                          <span className="text-[11px] text-slate-500 block uppercase font-medium">
                            Plans starting at
                          </span>
                          <div className="flex items-baseline gap-1">
                            <span className="text-xl font-extrabold text-ink-navy dark:text-white">₹{startingPrice}</span>
                            <span className="text-xs text-slate-500 dark:text-slate-400">/ 1 Month</span>
                          </div>
                        </>
                      )}
                    </div>

                    {isOwned ? (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleOpenSubjectModal(subject, true); }}
                        className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-signal-emerald/10 hover:bg-signal-emerald text-signal-emerald hover:text-white text-xs font-bold transition-all duration-200"
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                        <span>Extend Plan</span>
                      </button>
                    ) : (
                      <div className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-emerald-500/10 group-hover:bg-emerald-500 text-emerald-400 group-hover:text-slate-950 text-xs font-bold transition-all duration-200">
                        <span>Select</span>
                        <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                      </div>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </section>



      {/* ─── Interactive Selection & Smart Upsell Modal (Drawer / Popup) ─── */}
      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-y-auto">
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsModalOpen(false)}
              className="fixed inset-0 bg-slate-50 dark:bg-slate-950/80 backdrop-blur-md"
            />

            {/* Modal Container */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="relative w-full max-w-4xl bg-white dark:bg-slate-900 border border-white/15 rounded-3xl shadow-2xl overflow-hidden z-10 flex flex-col max-h-[90vh]"
            >
              {/* Modal Header */}
              <div className="p-6 sm:px-8 border-b border-white/10 flex items-center justify-between bg-white/90 dark:bg-slate-900/90 backdrop-blur-xl">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 text-xs font-bold uppercase">
                      {activeLevel} Package {isExtendMode ? "Extension" : "Customizer"}
                    </span>
                    <span className="text-slate-500">•</span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {modalSelectedSubjectIds.length}{" "}
                      {modalSelectedSubjectIds.length === 1 ? "Subject" : "Subjects"} Selected
                    </span>
                  </div>
                  <h3 className="text-xl sm:text-2xl font-bold text-ink-navy dark:text-white mt-1">
                    {isExtendMode ? "Extend Your Access — Choose Duration" : "Choose Duration & Unlock Instant Practice"}
                  </h3>
                </div>

                <button
                  onClick={() => setIsModalOpen(false)}
                  className="p-2 rounded-xl bg-slate-100 dark:bg-black/5 dark:bg-white/5 hover:bg-black/10 dark:bg-white/10 text-slate-500 dark:text-slate-400 hover:text-ink-navy dark:text-white transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Modal Body (Scrollable) */}
              <div className="p-6 sm:p-8 overflow-y-auto space-y-8">
                {/* ─── Step 1: Smart Upsell Recommendation Banner (If available) ─── */}
                {cartCalculation.upsellRecommendation && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="relative rounded-2xl p-5 bg-gradient-to-r from-emerald-950/70 via-teal-950/60 to-slate-900 border border-emerald-500/40 shadow-xl overflow-hidden"
                  >
                    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                      <div className="flex items-start gap-3">
                        <div className="p-2.5 rounded-xl bg-emerald-500/20 text-emerald-300 shrink-0">
                          <Sparkles className="w-5 h-5 animate-spin-slow" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-black uppercase tracking-wider text-emerald-400">
                              Smart Recommendation
                            </span>
                            <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 text-[10px] font-bold">
                              Save ₹{cartCalculation.upsellRecommendation.savings}
                            </span>
                          </div>
                          <h4 className="text-sm sm:text-base font-bold text-ink-navy dark:text-white mt-0.5">
                            {cartCalculation.upsellRecommendation.bundleTitle}
                          </h4>
                          <p className="text-xs text-slate-600 dark:text-slate-300 mt-1">
                            {cartCalculation.upsellRecommendation.message}
                          </p>
                        </div>
                      </div>

                      {/* Upgrade Action Button with Strikethrough Pricing */}
                      <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
                        <div className="text-right">
                          <del className="text-xs text-slate-500 dark:text-slate-400 font-semibold block">
                            ₹{cartCalculation.upsellRecommendation.originalSum}
                          </del>
                          <span className="text-base font-extrabold text-emerald-400">
                            ₹{cartCalculation.upsellRecommendation.bundlePrice}
                          </span>
                        </div>
                        <button
                          onClick={() =>
                            handleApplyUpsell(cartCalculation.upsellRecommendation!.subjectIds)
                          }
                          className="px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-extrabold shadow-lg shadow-emerald-500/20 hover:scale-105 transition-all"
                        >
                          Upgrade to Bundle
                        </button>
                      </div>
                    </div>
                  </motion.div>
                )}

                {/* ─── Step 2: Duration Selector ─── */}
                <div>
                  <label className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 block mb-3">
                    Step 1: Select Access Duration
                  </label>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {(["1_month", "3_months", "6_months", "1_year"] as PricingDuration[]).map(
                      (duration) => {
                        const isSelected = selectedDuration === duration;
                        const durationInfo = DURATION_LABELS[duration];
                        // Calculate price for this duration with current subjects
                        const tempCalc = calculateMCQCartPrice(
                          activeLevel,
                          modalSelectedSubjectIds,
                          duration,
                          allSubjects,
                          allBundles
                        );

                        return (
                          <button
                            key={duration}
                            onClick={() => setSelectedDuration(duration)}
                            className={`relative p-4 rounded-2xl text-left border transition-all duration-200 flex flex-col justify-between ${isSelected
                              ? "bg-emerald-500/10 border-emerald-500 shadow-lg shadow-emerald-500/10"
                              : "bg-slate-800/40 border-white/10 hover:border-white/20"
                              }`}
                          >
                            {/* Duration Tag */}
                            <div className="flex items-center justify-between w-full mb-3">
                              <span className="text-xs font-extrabold text-ink-navy dark:text-white">
                                {durationInfo.label}
                              </span>
                              <span
                                className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${isSelected
                                  ? "bg-emerald-500 text-slate-950"
                                  : "bg-black/10 dark:bg-white/10 text-slate-600 dark:text-slate-300"
                                  }`}
                              >
                                {durationInfo.tag}
                              </span>
                            </div>

                            {/* Price */}
                            <div>
                              <div className="flex items-baseline gap-1">
                                <span className="text-xl font-black text-ink-navy dark:text-white">
                                  ₹{tempCalc.discountedPrice}
                                </span>
                              </div>
                              {tempCalc.savingsAmount > 0 && (
                                <span className="text-[10px] text-emerald-400 font-semibold block mt-0.5">
                                  Save ₹{tempCalc.savingsAmount}
                                </span>
                              )}
                            </div>
                          </button>
                        );
                      }
                    )}
                  </div>
                </div>

                {/* ─── Step 3: Included / Selected Subjects Multi-Toggle ─── */}
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <label className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Step 2: Selected Subjects in Package
                    </label>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      Click to add or remove subjects
                    </span>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-3">
                    {levelSubjects.map((sub) => {
                      const isAlreadyOwned = ownedMcqSubjects.includes(sub.id) || ownedMcqSubjects.includes(sub.code);
                      const isIncluded = modalSelectedSubjectIds.includes(sub.id) || isAlreadyOwned;
                      const subPrice = sub.prices[selectedDuration] || 0;

                      return (
                        <div
                          key={sub.id}
                          onClick={() => {
                            if (isAlreadyOwned) return;
                            handleToggleSubject(sub.id);
                          }}
                          className={`p-3.5 rounded-2xl border transition-all flex items-center justify-between ${isAlreadyOwned
                            ? "bg-emerald-500/10 border-emerald-500/30 opacity-70 cursor-not-allowed"
                            : isIncluded
                              ? "bg-black/10 dark:bg-white/10 border-emerald-500/60 shadow-sm cursor-pointer"
                              : "bg-slate-800/30 border-white/5 opacity-60 hover:opacity-100 hover:border-white/20 cursor-pointer"
                            }`}
                        >
                          <div className="flex items-center gap-3">
                            <div
                              className={`w-5 h-5 rounded-lg flex items-center justify-center border text-xs font-bold ${isAlreadyOwned
                                ? "bg-emerald-500/50 border-emerald-500/50 text-white"
                                : isIncluded
                                  ? "bg-emerald-500 border-emerald-500 text-slate-950"
                                  : "border-white/20 bg-transparent text-transparent"
                                }`}
                            >
                              <Check className="w-3.5 h-3.5 stroke-[3]" />
                            </div>
                            <div>
                              <span className="text-xs font-bold text-ink-navy dark:text-white block">
                                {sub.name}
                              </span>
                              {isAlreadyOwned ? (
                                <span className="text-[9px] text-emerald-500 dark:text-emerald-400 uppercase tracking-widest font-bold">
                                  Already Unlocked
                                </span>
                              ) : (
                                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                                  {sub.code} • {sub.groupName}
                                </span>
                              )}
                            </div>
                          </div>

                          <div className="text-right">
                            {isAlreadyOwned ? (
                              <span className="text-xs font-bold text-emerald-500 line-through opacity-70">₹{subPrice}</span>
                            ) : (
                              <span className="text-xs font-black text-ink-navy dark:text-white">₹{subPrice}</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* ─── Step 4: Summary & Coupon ─── */}
                <div className="p-6 rounded-2xl bg-slate-50 dark:bg-slate-950/70 border border-white/10 space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/10">
                    {/* Coupon Input */}
                    <div className="flex-1 max-w-sm">
                      <label className="text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider block mb-1.5">
                        Have a Coupon Code?
                      </label>
                      <div className="flex gap-2">
                        <div className="relative flex-1">
                          <Tag className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />
                          <input
                            type="text"
                            placeholder="e.g. CALIBER10"
                            value={couponCode}
                            onChange={(e) => setCouponCode(e.target.value)}
                            disabled={couponApplied}
                            className="w-full pl-9 pr-3 py-2 text-xs bg-white dark:bg-slate-900 border border-white/10 rounded-xl text-ink-navy dark:text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 uppercase font-mono"
                          />
                        </div>
                        {couponApplied ? (
                          <button
                            onClick={() => {
                              setCouponApplied(false);
                              setCouponDiscount(0);
                              setCouponCode("");
                            }}
                            className="px-3 py-2 bg-red-500/10 text-red-400 text-xs font-bold rounded-xl hover:bg-red-500/20 transition-all"
                          >
                            Remove
                          </button>
                        ) : (
                          <button
                            onClick={handleApplyCoupon}
                            disabled={couponLoading}
                            className="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-extrabold rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {couponLoading ? "..." : "Apply"}
                          </button>
                        )}
                      </div>
                      {couponApplied && (
                        <span className="text-[11px] text-emerald-400 font-semibold block mt-1">
                          ✓ Coupon applied! Saved ₹{couponDiscount}
                        </span>
                      )}
                      {couponError && (
                        <span className="text-[11px] text-red-400 font-medium block mt-1">
                          {couponError}
                        </span>
                      )}
                    </div>

                    {/* Price Breakdown */}
                    <div className="text-right space-y-1 sm:w-60">
                      <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400">
                        <span>Original Total:</span>
                        <span>₹{cartCalculation.realTotalPrice}</span>
                      </div>

                      {cartCalculation.savingsAmount > 0 && (
                        <div className="flex justify-between text-xs text-emerald-400 font-semibold">
                          <span>
                            {cartCalculation.appliedBundle
                              ? `${cartCalculation.appliedBundle.title} Discount:`
                              : "Bundle Savings:"}
                          </span>
                          <span>-₹{cartCalculation.savingsAmount}</span>
                        </div>
                      )}

                      {couponDiscount > 0 && (
                        <div className="flex justify-between text-xs text-cyan-400 font-semibold">
                          <span>Coupon Discount:</span>
                          <span>-₹{couponDiscount}</span>
                        </div>
                      )}

                      <div className="pt-2 border-t border-white/10 flex justify-between items-baseline">
                        <span className="text-sm font-bold text-ink-navy dark:text-white">Final Payable:</span>
                        <div className="flex items-baseline gap-1.5">
                          {cartCalculation.realTotalPrice > finalPayablePrice && (
                            <del className="text-xs text-slate-500">
                              ₹{cartCalculation.realTotalPrice}
                            </del>
                          )}
                          <span className="text-2xl font-black text-emerald-400">
                            ₹{finalPayablePrice}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Payment Gateways Selection — Test Mode only ever renders when
                      explicitly enabled via env, never in a normal production build */}
                  {process.env.NEXT_PUBLIC_ENABLE_TEST_PAYMENTS === "true" && (
                    <div className="flex bg-slate-900 border border-slate-700/50 p-1.5 rounded-xl mb-6 shadow-inner">
                      <button
                        onClick={() => setActivePaymentMethod("razorpay")}
                        className={`flex-1 flex gap-2 justify-center items-center py-2 text-xs font-bold rounded-lg transition-all ${activePaymentMethod === "razorpay"
                          ? "bg-slate-700 text-white shadow"
                          : "text-slate-400 hover:text-white"
                          }`}
                      >
                        <CreditCard className="w-3.5 h-3.5" /> Razorpay
                      </button>
                      <button
                        onClick={() => setActivePaymentMethod("manual")}
                        className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all ${activePaymentMethod === "manual"
                          ? "bg-emerald-500 text-slate-950 shadow"
                          : "text-slate-400 hover:text-white"
                          }`}
                      >
                        Test Mode (Manual)
                      </button>
                    </div>
                  )}

                  {/* Checkout Button & Security Badges */}
                  <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
                    <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
                      <span className="flex items-center gap-1.5">
                        <ShieldCheck className="w-4 h-4 text-emerald-400" /> 256-Bit Encrypted
                      </span>
                      <span className="flex items-center gap-1.5">
                        <Clock className="w-4 h-4 text-cyan-400" /> Instant Activation
                      </span>
                    </div>

                    {(paymentMode === "manual" || paymentMode === "both") && (
                      <button
                        onClick={() => (isAuthenticated ? setShowUpiModal(true) : router.push("/login?next=/mcq"))}
                        disabled={modalSelectedSubjectIds.length === 0}
                        className="w-full sm:w-auto px-8 py-3.5 rounded-2xl bg-gradient-to-r from-emerald-400 via-teal-400 to-cyan-400 hover:from-emerald-300 hover:to-cyan-300 text-slate-950 text-sm font-black shadow-xl shadow-emerald-500/20 hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                      >
                        <CreditCard className="w-4 h-4" />
                        <span>Pay via UPI — ₹{finalPayablePrice}</span>
                      </button>
                    )}
                    {(paymentMode === "razorpay" || paymentMode === "both") && (
                      <button
                        onClick={handleCheckout}
                        disabled={isProcessing || modalSelectedSubjectIds.length === 0}
                        className={`w-full sm:w-auto px-8 py-3.5 rounded-2xl text-sm font-black transition-all flex items-center justify-center gap-2 disabled:opacity-50 ${
                          paymentMode === "both"
                            ? "border border-slate-700/50 text-slate-300 hover:bg-slate-800"
                            : "bg-gradient-to-r from-emerald-400 via-teal-400 to-cyan-400 hover:from-emerald-300 hover:to-cyan-300 text-slate-950 shadow-xl shadow-emerald-500/20 hover:scale-[1.02] active:scale-[0.98]"
                        }`}
                      >
                        {isProcessing ? (
                          <>
                            <RefreshCw className="w-4 h-4 animate-spin" />
                            <span>Processing Checkout...</span>
                          </>
                        ) : (
                          <>
                            <CreditCard className="w-4 h-4" />
                            <span>Proceed to Pay ₹{finalPayablePrice}</span>
                          </>
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* ─── Success Activation Confirmation Modal ─── */}
      <AnimatePresence>
        {purchaseSuccess && purchasedInfo && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-slate-50 dark:bg-slate-950/80 backdrop-blur-md"
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="relative w-full max-w-md bg-white dark:bg-slate-900 border border-emerald-500/40 rounded-3xl p-8 shadow-2xl text-center z-10"
            >
              <div className="w-16 h-16 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center mx-auto mb-4 text-emerald-400">
                <Check className="w-8 h-8 stroke-[3]" />
              </div>

              <h3 className="text-2xl font-bold text-ink-navy dark:text-white">Package Activated!</h3>
              <p className="text-sm text-slate-600 dark:text-slate-300 mt-2">
                Your <strong className="text-emerald-400">{purchasedInfo.title}</strong> has been
                unlocked with full unlimited test attempts.
              </p>

              <div className="mt-6 p-4 rounded-2xl bg-slate-100 dark:bg-black/5 dark:bg-white/5 border border-white/10 text-xs text-slate-600 dark:text-slate-300 space-y-1 text-left">
                <div className="flex justify-between">
                  <span>Amount Paid:</span>
                  <span className="font-bold text-ink-navy dark:text-white">₹{purchasedInfo.amount}</span>
                </div>
                <div className="flex justify-between">
                  <span>Access Duration:</span>
                  <span className="font-bold text-ink-navy dark:text-white">{DURATION_LABELS[selectedDuration].label}</span>
                </div>
                <div className="flex justify-between">
                  <span>Status:</span>
                  <span className="font-bold text-emerald-400">Active / Unlimited</span>
                </div>
              </div>

              <div className="mt-6 flex flex-col gap-2">
                <button
                  onClick={() => {
                    setPurchaseSuccess(false);
                    setIsModalOpen(false);
                    window.location.href = "/dashboard?tab=mcqs";
                  }}
                  className="w-full py-3 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-sm transition-all"
                >
                  Start Practicing Now
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
