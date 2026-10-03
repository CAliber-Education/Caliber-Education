"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "@/context/AuthContext";
import { isStaffPanelRole } from "@/lib/roles";
import { Toast, type ToastState } from "@/components/Toast";
import {
  BookOpen,
  Lock,
  Unlock,
  Zap,
  Star,
  TrendingUp,
  Calendar,
  Shield,
  ArrowRight,
  ChevronRight,
  BarChart2,
  Clock,
  MessageCircle,
  X,
  Copy,
  Check,
  AlertTriangle,
  Video
} from "lucide-react";

function calculateDaysLeft(expiryIso?: string) {
  if (!expiryIso) return null;
  const ms = new Date(expiryIso).getTime() - Date.now();
  if (ms <= 0) return 0;
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
}

export default function DashboardPage() {
  const {
    user,
    isAuthenticated,
    isMounted,
    purchasedCourseIds,
  } = useAuth();

  const router = useRouter();

  const [accessCourseId, setAccessCourseId] = useState<string | null>(null);
  const [copiedLink, setCopiedLink] = useState(false);
  const [realWhatsappLink, setRealWhatsappLink] = useState<string | null>(null);
  const [whatsappLinkError, setWhatsappLinkError] = useState("");
  const [toast, setToast] = useState<ToastState | null>(null);
  const [loadingWhatsappLink, setLoadingWhatsappLink] = useState(false);

  useEffect(() => {
    if (!accessCourseId) { setRealWhatsappLink(null); setWhatsappLinkError(""); return; }
    setLoadingWhatsappLink(true);
    setWhatsappLinkError("");
    const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
    const token = localStorage.getItem("caliber_jwt") || "";
    fetch(`${apiURL}/api/courses/${accessCourseId}/whatsapp-access`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => {
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || "WhatsApp link isn't set up for this course yet.");
        }
        return r.json();
      })
      .then((d) => setRealWhatsappLink(d.whatsappLink))
      .catch((e) => setWhatsappLinkError(e.message || "Couldn't load your WhatsApp link."))
      .finally(() => setLoadingWhatsappLink(false));
  }, [accessCourseId]);

  useEffect(() => {
    if (!accessCourseId) return;
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === "Escape") setAccessCourseId(null); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [accessCourseId]);

  // Read active tab from URL on mount safely
  const [activeTab, setActiveTab] = useState<"courses" | "mcqs" | "test-series" | "sessions" | "results">("courses");
  useEffect(() => {
    if (typeof window !== "undefined") {
      const urlParams = new URLSearchParams(window.location.search);
      const tab = urlParams.get("tab");
      if (tab === "mcqs" || tab === "test-series" || tab === "results" || tab === "courses" || tab === "sessions") {
        setActiveTab(tab);
      }
    }
  }, []);

  // 1:1 Sessions States
  const [sessions, setSessions] = useState<any[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);

  // Test Evaluation States
  const [submissions, setSubmissions] = useState<any[]>([]);
  const [loadingTests, setLoadingTests] = useState(true);

  // Profile States
  const [profileDetails, setProfileDetails] = useState<any>({});
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileForm, setProfileForm] = useState({
    full_name: "", phone_number: "", address: "", stage: "CA Final", attempt_status: "First Attempt"
  });

  const [dbScrapedSeries, setDbScrapedSeries] = useState<any[]>([]);
  const [dbCourses, setDbCourses] = useState<any[]>([]);
  const [loadingCourses, setLoadingCourses] = useState(true);
  const [loadingMcqSeries, setLoadingMcqSeries] = useState(true);
  const [myTestSeries, setMyTestSeries] = useState<any[]>([]);
  const [loadingTestSeries, setLoadingTestSeries] = useState(true);
  const [attempts, setAttempts] = useState<any[]>([]);

  useEffect(() => {
    const fetchCourses = async () => {
      setLoadingCourses(true);
      try {
        const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
        const res = await fetch(`${apiURL}/api/courses`);
        if (res.ok) {
          const data = await res.json();
          setDbCourses(data);
        }
      } catch (e) {
        console.warn("Failed to fetch live courses", e);
      } finally {
        setLoadingCourses(false);
      }
    };
    fetchCourses();
  }, []);

  const fetchMcqSeries = async () => {
    setLoadingMcqSeries(true);
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";
      const res = await fetch(`${apiURL}/api/mcq/my-subjects`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setDbScrapedSeries(data);
      }
    } catch (e) {
      console.warn("Failed to fetch MCQ series", e);
    } finally {
      setLoadingMcqSeries(false);
    }
  };

  useEffect(() => {
    fetchMcqSeries();
  }, []);

  // Re-fetch MCQ data every time user switches to the MCQs tab
  useEffect(() => {
    if (activeTab === "mcqs") {
      fetchMcqSeries();
    }
  }, [activeTab]);

  const fetchMyTestSeries = async () => {
    setLoadingTestSeries(true);
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";
      const res = await fetch(`${apiURL}/api/test-series/my-subjects`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        setMyTestSeries(await res.json());
      }
    } catch (e) {
      console.warn("Failed to fetch owned test series subjects", e);
    } finally {
      setLoadingTestSeries(false);
    }
  };

  useEffect(() => {
    if (!isAuthenticated) return;
    fetchMyTestSeries();
  }, [isAuthenticated]);

  useEffect(() => {
    if (isMounted && !isAuthenticated) router.push("/login");
  }, [isMounted, isAuthenticated, router]);

  // Load User Profile Data
  useEffect(() => {
    if (!isAuthenticated) return;
    const fetchProfile = async () => {
      try {
        const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
        const token = localStorage.getItem("caliber_jwt") || "";
        const res = await fetch(`${apiURL}/api/auth/me`, { headers: { "Authorization": `Bearer ${token}` } });
        if (res.ok) {
          const data = await res.json();
          setProfileDetails(data.user);
          setProfileForm({
            full_name: data.user.full_name || "",
            phone_number: data.user.phone_number || "",
            address: data.user.address || "",
            stage: data.user.stage || "CA Final",
            attempt_status: data.user.attempt_status || "First Attempt"
          });
          setAttempts(data.attempts || []);
        }
      } catch (err) {
        console.warn("Could not load user profile details");
      }
    };
    fetchProfile();
  }, [isAuthenticated]);

  // Load Sessions
  useEffect(() => {
    if (!isAuthenticated) return;
    const fetchSessions = async () => {
      setLoadingSessions(true);
      try {
        const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
        const token = localStorage.getItem("caliber_jwt") || "";

        const res = await fetch(`${apiURL}/api/sessions`, {
          headers: { "Authorization": `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          setSessions(data.sessions || data);
        } else {
          throw new Error("Unable to fetch sessions");
        }
      } catch (err) {
        console.warn("API request failed:", err);
        setSessions([]);
      } finally {
        setLoadingSessions(false);
      }
    };
    fetchSessions();
  }, [isAuthenticated]);

  // Load the student's test series submissions/evaluations
  useEffect(() => {
    if (!isAuthenticated) return;
    const fetchSubmissions = async () => {
      setLoadingTests(true);
      try {
        const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
        const token = localStorage.getItem("caliber_jwt") || "";
        const res = await fetch(`${apiURL}/api/tests/submissions`, { headers: { "Authorization": `Bearer ${token}` } });
        if (!res.ok) throw new Error("Unable to fetch submissions from server");
        setSubmissions(await res.json());
      } catch (err) {
        console.warn("Fetching submissions failed:", err);
        setSubmissions([]);
      } finally {
        setLoadingTests(false);
      }
    };
    fetchSubmissions();
  }, [isAuthenticated]);

  const handleCancelSession = async (sessionId: string) => {
    const confirm = window.confirm("Are you sure you want to cancel this booking?");
    if (!confirm) return;

    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";

      const res = await fetch(`${apiURL}/api/sessions/${sessionId}/cancel`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        setSessions(prev => prev.filter(s => s.id !== sessionId));
      } else {
        const d = await res.json().catch(() => ({}));
        setToast({ type: "error", message: d.detail || "Couldn't cancel this session. Please try again." });
      }
    } catch (err) {
      setToast({ type: "error", message: "Couldn't cancel this session. Please check your connection and try again." });
    }
  };

  if (!isMounted || !isAuthenticated || !user) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-paper/40 dark:bg-ink-navy/40 backdrop-blur-md transition-all duration-500">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-line-gray-light dark:border-line-gray-dark border-t-ink-navy dark:border-t-signal-emerald rounded-full animate-spin"></div>
          <p className="text-[10px] font-bold font-heading text-ink-navy dark:text-paper uppercase tracking-widest animate-pulse">
            Preparing your workspace
          </p>
        </div>
      </div>
    );
  }

  const isAdmin = isStaffPanelRole(user.role);

  const userPurchasedCourses = dbCourses.filter((c: any) => purchasedCourseIds.includes(c.id));
  const totalMyCourses = userPurchasedCourses.length;

  const activeAccessCourse = dbCourses.find((c: any) => c.id === accessCourseId);

  const handleCopyLink = () => {
    if (!realWhatsappLink) return;
    navigator.clipboard.writeText(realWhatsappLink);
    setCopiedLink(true);
    setTimeout(() => setCopiedLink(false), 2000);
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingProfile(true);
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";
      const res = await fetch(`${apiURL}/api/auth/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify(profileForm)
      });
      if (res.ok) {
        setProfileDetails((prev: any) => ({ ...prev, ...profileForm }));
        setShowProfileModal(false);
      } else {
        setToast({ type: "error", message: "Could not update profile because database schema was not updated yet. Please contact support." });
      }
    } catch (err) {
      setToast({ type: "error", message: "Error saving profile" });
    } finally {
      setSavingProfile(false);
    }
  };

  return (
    <div className="pt-16 pb-20 min-h-screen bg-paper dark:bg-ink-navy/10">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <div className="max-w-6xl mx-auto px-6 sm:px-8 py-10 space-y-8">

        {/* Greeting Banner */}
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <p className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate dark:text-paper/40">Dashboard</p>
              <h1 className="font-heading font-extrabold text-2xl sm:text-3xl text-ink-navy dark:text-paper leading-none">
                Welcome back{profileDetails?.full_name ? `, ${profileDetails.full_name.split(' ')[0]}` : ''} 👋
              </h1>
              <div className="flex items-center gap-3">
                <p className="text-xs font-semibold text-slate dark:text-paper/60">{user.email}</p>
              </div>
            </div>

            {isAdmin && (
              <div className="flex flex-col items-start sm:items-end gap-2">
                <div className="flex items-center gap-3 px-4 py-2 rounded-lg border bg-alert-coral/5 border-alert-coral/25">
                  <Shield className="w-4 h-4 text-alert-coral" />
                  <span className="text-xs font-semibold text-alert-coral capitalize">{user.role === "mcq_editor" ? "MCQ Editor" : user.role.replace("_", " ")}</span>
                </div>
                <Link
                  href="/admin"
                  className="flex items-center gap-1 text-[10px] font-bold text-alert-coral uppercase tracking-wider hover:underline"
                >
                  Go to Admin panel <ChevronRight className="w-3 h-3" />
                </Link>
              </div>
            )}
          </div>
        </motion.div>

        {/* Stats Summary Panel - Temporarily removed because it uses mock data and student hasn't attempted anything yet */}

        {/* Dynamic Tab Selector Switch */}
        <div className="flex gap-4 border-b border-line-gray-light dark:border-line-gray-dark pb-px pt-2">
          {[
            { id: "courses", label: "My Courses" },
            { id: "mcqs", label: "My MCQs" },
            { id: "test-series", label: "My Test Series" },
            { id: "sessions", label: "My 1:1 Sessions" },
            { id: "results", label: "My Results Analysis" }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`pb-3 text-xs font-bold uppercase tracking-wider border-b-2 px-1 transition-all ${activeTab === tab.id
                ? "border-ink-navy dark:border-paper text-ink-navy dark:text-paper"
                : "border-transparent text-slate/50 dark:text-paper/40 hover:text-slate dark:hover:text-paper/70"
                }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Render Active Tab Panels */}
        <AnimatePresence mode="wait">
          {activeTab === "courses" && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-12">
              {/* My Courses */}
              <div className="space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-end justify-between border-b border-line-gray-light dark:border-line-gray-dark pb-3 gap-4">
                  <div>
                    <h2 className="font-heading font-bold text-base text-ink-navy dark:text-paper">Current Courses</h2>
                    <span className="text-[10px] text-slate dark:text-paper/45 mt-0.5 block">{totalMyCourses} enrolled</span>
                  </div>

                  <div className="bg-gradient-to-r from-signal-emerald/20 to-emerald-400/10 px-4 py-2.5 rounded-xl border border-signal-emerald/30 inline-flex flex-col sm:flex-row items-center gap-3 w-full sm:w-auto">
                    <div className="text-center sm:text-left">
                      <p className="text-xs font-bold text-emerald-700 dark:text-emerald-400 leading-tight">Buy single course or buy more and get discount!</p>
                      <p className="text-[9px] text-emerald-700/70 dark:text-emerald-400/70">Group 1 & 2 combinations are available.</p>
                    </div>
                    <Link href="/courses" className="px-3 py-1.5 bg-signal-emerald text-white text-xs font-bold rounded-lg hover:opacity-90 transition-all whitespace-nowrap shadow-sm border border-emerald-600/50">
                      View Bundles
                    </Link>
                  </div>
                </div>

                {loadingCourses ? (
                  <div className="grid sm:grid-cols-2 gap-6">
                    {[0, 1].map((i) => (
                      <div key={i} className="p-5 border border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/20 space-y-3 animate-pulse">
                        <div className="h-2.5 w-20 bg-line-gray-light dark:bg-line-gray-dark rounded" />
                        <div className="h-4 w-3/4 bg-line-gray-light dark:bg-line-gray-dark rounded" />
                        <div className="h-2.5 w-1/2 bg-line-gray-light dark:bg-line-gray-dark rounded" />
                      </div>
                    ))}
                  </div>
                ) : totalMyCourses === 0 ? (
                  <div className="p-8 text-center border border-dashed border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/10 space-y-3">
                    <p className="text-xs text-slate dark:text-paper/50">You haven't enrolled in any CA prep courses yet.</p>
                    <Link href="/courses" className="inline-flex items-center gap-1.5 px-4 py-2 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy text-xs font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all">
                      Browse Courses <ArrowRight className="w-3.5 h-3.5" />
                    </Link>
                  </div>
                ) : (
                  <div className="grid sm:grid-cols-2 gap-6">
                    {/* Enrolled Courses */}
                    {userPurchasedCourses.map((c) => (
                      <div key={c.id} className="p-5 border border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/20 flex flex-col justify-between gap-4">
                        <div className="space-y-1.5">
                          <span className="text-[9px] font-bold uppercase tracking-wider text-signal-emerald">Active Access</span>
                          <h3 className="font-heading font-bold text-sm text-ink-navy dark:text-paper">{c.title}</h3>
                          <p className="text-[10px] text-slate dark:text-paper/50">{c.level}{c.duration ? ` · ${c.duration}` : ""}</p>
                        </div>
                        <div className="flex items-center gap-2 pt-2 border-t border-line-gray-light/30 dark:border-line-gray-dark/30">
                          <button
                            onClick={() => setAccessCourseId(c.id)}
                            className="flex-1 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-lg text-xs transition-all flex items-center justify-center gap-1 active:scale-[0.98] whitespace-nowrap"
                          >
                            <MessageCircle className="w-3.5 h-3.5 flex-shrink-0" /> WhatsApp Access
                          </button>
                          <Link
                            href={`/courses/${c.id}`}
                            className="flex-shrink-0 px-3 py-1.5 border border-line-gray-light dark:border-line-gray-dark text-slate dark:text-paper/70 hover:text-ink-navy dark:hover:text-paper rounded-lg text-xs font-semibold transition-all text-center whitespace-nowrap"
                          >
                            View
                          </Link>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )}

          {activeTab === "mcqs" && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-8">
              {/* Practice Library */}
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-line-gray-light dark:border-line-gray-dark pb-2">
                  <h2 className="font-heading font-bold text-base text-ink-navy dark:text-paper">Practice Library</h2>
                  <span className="text-xs text-slate dark:text-paper/45">{dbScrapedSeries.length} series</span>
                </div>

                {loadingMcqSeries ? (
                  <div className="grid sm:grid-cols-2 gap-4">
                    {[0, 1].map((i) => (
                      <div key={i} className="p-4 border border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/20 flex items-center gap-4 animate-pulse">
                        <div className="w-10 h-10 rounded bg-line-gray-light dark:bg-line-gray-dark flex-shrink-0" />
                        <div className="flex-1 space-y-2">
                          <div className="h-3 w-2/3 bg-line-gray-light dark:bg-line-gray-dark rounded" />
                          <div className="h-2.5 w-1/3 bg-line-gray-light dark:bg-line-gray-dark rounded" />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : dbScrapedSeries.length === 0 ? (
                  <div className="p-8 text-center border border-dashed border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/10 space-y-3">
                    <p className="text-xs text-slate dark:text-paper/50">You haven't unlocked any MCQ subjects yet.</p>
                    <Link href="/mcq" className="inline-flex items-center gap-1.5 px-4 py-2 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy text-xs font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all">
                      Browse MCQ Modules <ArrowRight className="w-3.5 h-3.5" />
                    </Link>
                  </div>
                ) : (
                  <div className="grid sm:grid-cols-2 gap-4">
                    {dbScrapedSeries.map((series, i) => {
                      const days = calculateDaysLeft(series.access_until);
                      return (
                      <div
                        key={series.id}
                        className="flex items-center justify-between p-4 bg-white dark:bg-line-gray-dark/20 border border-line-gray-light dark:border-line-gray-dark rounded-xl hover:border-slate/50 dark:hover:border-paper transition-all duration-200 group"
                      >
                        <div className="flex items-center gap-4 min-w-0">
                          {/* Avatar — use short subject code */}
                          <div className="flex-shrink-0 w-10 h-10 rounded bg-signal-emerald/10 border border-signal-emerald/20 text-signal-emerald flex items-center justify-center text-[10px] font-black font-mono uppercase">
                            {String(series.code || series.id).slice(0, 3)}
                          </div>

                          <div className="min-w-0 space-y-1">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <p className="font-semibold text-xs text-ink-navy dark:text-paper truncate">{series.title}</p>
                              {/* Enrollment status badge — not Free/Paid */}
                              <span className="text-[8px] font-bold px-1.5 py-0.5 rounded bg-signal-emerald/10 text-signal-emerald flex-shrink-0">
                                Enrolled
                              </span>
                            </div>

                            {/* Subject info + validity */}
                            <div className="flex items-center gap-2 flex-wrap">
                              <p className="text-[10px] text-slate dark:text-paper/40">{series.subject}</p>
                            </div>

                            {/* Expiry row — always show something */}
                            <div className="flex items-center gap-2 flex-wrap">
                              {series.access_until ? (
                                <>
                                  {days !== null && days <= 0 ? (
                                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-alert-coral/15 text-alert-coral">
                                      Expired
                                    </span>
                                  ) : days !== null && days <= 7 ? (
                                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-alert-coral/15 text-alert-coral">
                                      ⚠ {days}d left
                                    </span>
                                  ) : days !== null && days <= 30 ? (
                                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400">
                                      {days}d left
                                    </span>
                                  ) : days !== null ? (
                                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-signal-emerald/10 text-signal-emerald">
                                      {days}d left
                                    </span>
                                  ) : null}
                                  <span className="text-[9px] text-slate/50 dark:text-paper/30">
                                    expires {new Date(series.access_until).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                                  </span>
                                </>
                              ) : (
                                <span className="text-[9px] text-slate/40 dark:text-paper/25 italic">No expiry set — contact admin</span>
                              )}
                            </div>
                          </div>
                        </div>

                        <div className="flex-shrink-0 pl-3 flex items-center gap-2">
                          <Link
                            href={`/mcq?extend=${series.id}`}
                            className="text-[9px] font-bold text-slate/50 dark:text-paper/30 hover:text-signal-emerald transition-colors hidden sm:block"
                          >
                            Extend
                          </Link>
                          <Link
                            href={`/mcq/${series.id}`}
                            className="flex items-center gap-1 text-xs font-semibold text-ink-navy dark:text-paper hover:underline"
                          >
                            <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
                            Enter
                          </Link>
                        </div>
                      </div>
                      );
                    })}
                  </div>
                )}
              </div>

            </motion.div>
          )}

          {activeTab === "test-series" && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-4">
              <div className="flex items-center justify-between border-b border-line-gray-light dark:border-line-gray-dark pb-2">
                <h2 className="font-heading font-bold text-base text-ink-navy dark:text-paper">Test Series</h2>
                <span className="text-xs text-slate dark:text-paper/45">{myTestSeries.length} subject{myTestSeries.length === 1 ? "" : "s"}</span>
              </div>

              {loadingTestSeries ? (
                <div className="grid sm:grid-cols-2 gap-4">
                  {[0, 1].map((i) => (
                    <div key={i} className="p-4 border border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/20 flex items-center gap-4 animate-pulse">
                      <div className="w-10 h-10 rounded bg-line-gray-light dark:bg-line-gray-dark flex-shrink-0" />
                      <div className="flex-1 space-y-2">
                        <div className="h-3 w-2/3 bg-line-gray-light dark:bg-line-gray-dark rounded" />
                        <div className="h-2.5 w-1/3 bg-line-gray-light dark:bg-line-gray-dark rounded" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : myTestSeries.length === 0 ? (
                <div className="p-8 text-center border border-dashed border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/10 space-y-3">
                  <p className="text-xs text-slate dark:text-paper/50">You haven&apos;t purchased any test series subjects yet.</p>
                  <Link href="/test-series" className="inline-flex items-center gap-1.5 px-4 py-2 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy text-xs font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all">
                    Browse Test Series <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              ) : (
                <div className="grid sm:grid-cols-2 gap-4">
                  {myTestSeries.map((s) => (
                    <div
                      key={s.id}
                      className="flex items-center justify-between p-4 bg-white dark:bg-line-gray-dark/20 border border-line-gray-light dark:border-line-gray-dark rounded-xl hover:border-slate/50 dark:hover:border-paper transition-all duration-200 group"
                    >
                      <div className="flex items-center gap-4 min-w-0">
                        <div className="flex-shrink-0 w-10 h-10 rounded bg-signal-emerald/10 border border-signal-emerald/20 text-signal-emerald flex items-center justify-center text-[10px] font-black font-mono uppercase">
                          {String(s.code || s.id).slice(0, 3)}
                        </div>
                        <div className="min-w-0 space-y-1">
                          <p className="font-semibold text-xs text-ink-navy dark:text-paper truncate">{s.name}</p>
                          <p className="text-[10px] text-slate dark:text-paper/40">{s.level}</p>
                        </div>
                      </div>
                      <Link
                        href={`/test-series/${String(s.level || "").toLowerCase()}/${s.id}`}
                        className="flex-shrink-0 pl-3 flex items-center gap-1 text-xs font-semibold text-ink-navy dark:text-paper hover:underline"
                      >
                        <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
                        Enter
                      </Link>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}

          {activeTab === "sessions" && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-4">
              <div className="border-b border-line-gray-light dark:border-line-gray-dark pb-2">
                <h3 className="font-heading font-bold text-sm text-ink-navy dark:text-paper">My 1:1 Sessions</h3>
              </div>

              {loadingSessions ? (
                <p className="text-sm text-slate dark:text-paper/50">Loading your sessions...</p>
              ) : sessions.length === 0 ? (
                <div className="border border-line-gray-light dark:border-line-gray-dark rounded-xl p-8 text-center">
                  <p className="text-sm text-slate dark:text-paper/60">You haven&apos;t booked any 1:1 sessions yet.</p>
                  <Link href="/courses" className="text-xs font-bold text-signal-emerald hover:underline mt-2 inline-block">
                    Browse 1:1 sessions
                  </Link>
                </div>
              ) : (
                <div className="space-y-3">
                  {sessions.map((s: any) => (
                    <div key={s.id} className="p-4 bg-white dark:bg-line-gray-dark/20 border border-line-gray-light dark:border-line-gray-dark rounded-xl">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div className="min-w-0">
                          <p className="text-sm font-bold text-ink-navy dark:text-paper">{s.courseTitle}</p>
                          {s.mentorName && (
                            <p className="text-[11px] text-slate dark:text-paper/60 mt-0.5">
                              Mentor: {s.mentorName}{s.specialty ? ` · ${s.specialty}` : ""}
                            </p>
                          )}
                        </div>
                        <span className={`text-[10px] font-bold px-2 py-1 rounded-full ${s.status === "booked" ? "bg-signal-emerald/10 text-signal-emerald"
                          : s.status === "completed" ? "bg-slate/10 text-slate dark:text-paper/60"
                            : "bg-amber-500/10 text-amber-600"}`}>
                          {s.status === "pending_assignment" ? "Assigning mentor"
                            : s.status === "pending_schedule" ? "Mentor picking a time"
                              : s.status === "booked" ? "Scheduled"
                                : s.status === "completed" ? "Completed" : s.status}
                        </span>
                      </div>

                      {s.status === "booked" && (
                        <div className="mt-3 flex items-center gap-3 flex-wrap">
                          <span className="text-xs font-mono text-ink-navy dark:text-paper">
                            {s.datetime ? new Date(s.datetime).toLocaleString() : ""}
                          </span>
                          {s.meetLink && (
                            <a href={s.meetLink} target="_blank" rel="noopener noreferrer"
                              className="px-3 py-1.5 text-[11px] font-bold bg-signal-emerald text-white rounded-lg hover:bg-signal-emerald/90 transition-colors">
                              Join meeting
                            </a>
                          )}
                        </div>
                      )}

                      {s.status === "pending_assignment" && (
                        <p className="text-[11px] text-slate dark:text-paper/50 mt-2">
                          Payment received. We&apos;re assigning your mentor — you&apos;ll see the time here shortly.
                        </p>
                      )}
                      {s.status === "pending_schedule" && (
                        <p className="text-[11px] text-slate dark:text-paper/50 mt-2">
                          Your mentor is confirming a time slot. It&apos;ll appear here once set.
                        </p>
                      )}
                      {s.mentorNote && (
                        <p className="text-[11px] text-slate dark:text-paper/70 mt-2 bg-line-gray-light/40 dark:bg-line-gray-dark/30 p-2 rounded-lg">
                          {s.mentorNote}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}

          {activeTab === "results" && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="space-y-6">

              <div className="space-y-3">
                <div className="flex items-center justify-between border-b border-line-gray-light dark:border-line-gray-dark pb-2 flex-wrap gap-2">
                  <div>
                    <h3 className="font-heading font-bold text-sm text-ink-navy dark:text-paper font-heading">MCQ Attempts</h3>
                    <p className="text-[10px] text-slate dark:text-paper/40 mt-0.5">Your recent MCQ quiz scores.</p>
                  </div>
                  <Link href="/mcq"
                    className="px-3.5 py-1.5 text-xs font-bold bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy rounded-lg hover:opacity-90 transition-opacity">
                    Browse MCQs
                  </Link>
                </div>

                {attempts.length === 0 ? (
                  <div className="text-center py-8 text-xs text-slate/50 italic border border-dashed border-line-gray-light dark:border-line-gray-dark rounded-xl">
                    You haven&apos;t attempted any MCQ quizzes yet.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {attempts.map((a, i) => {
                      const pct = a.total > 0 ? Math.round((a.score / a.total) * 100) : 0;
                      return (
                        <div key={`${a.set_id}-${i}`} className="flex items-center justify-between p-4 border border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/20">
                          <div className="min-w-0">
                            <h4 className="font-heading font-bold text-sm text-ink-navy dark:text-paper truncate">{a.paperTitle || "MCQ Paper"}</h4>
                            <p className="text-[10px] text-slate dark:text-paper/40 mt-0.5">
                              {a.created_at ? new Date(a.created_at).toLocaleDateString("en-IN") : ""}
                            </p>
                          </div>
                          <div className="flex-shrink-0 text-right">
                            <strong className="text-ink-navy dark:text-paper text-sm font-bold font-mono">{a.score}</strong>
                            <span className="text-slate dark:text-paper/40 text-xs"> / {a.total}</span>
                            <p className="text-[9px] font-bold text-signal-emerald">{pct}%</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between border-b border-line-gray-light dark:border-line-gray-dark pb-2 flex-wrap gap-2">
                <div>
                  <h3 className="font-heading font-bold text-sm text-ink-navy dark:text-paper font-heading">Test Series Evaluations</h3>
                  <p className="text-[10px] text-slate dark:text-paper/40 mt-0.5">Your submitted answer sheets and mentor feedback.</p>
                </div>
                <Link href="/test-series"
                  className="px-3.5 py-1.5 text-xs font-bold bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy rounded-lg hover:opacity-90 transition-opacity">
                  Browse Test Series
                </Link>
              </div>

              {loadingTests ? (
                <div className="text-center py-6 text-xs text-slate/50">Loading your submissions...</div>
              ) : submissions.length === 0 ? (
                <div className="text-center py-8 text-xs text-slate/50 italic border border-dashed border-line-gray-light dark:border-line-gray-dark rounded-xl">
                  You haven&apos;t submitted any test series papers yet. Buy a subject and upload your answers from its page.
                </div>
              ) : (
                <div className="space-y-3">
                  {submissions.map((sub) => (
                    <div key={sub.id} className="p-4 border border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/20">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div>
                          <h4 className="font-heading font-bold text-sm text-ink-navy dark:text-paper">{sub.testTitle || "Test paper"}</h4>
                          <p className="text-[10px] text-slate dark:text-paper/40 mt-0.5">
                            Submitted {new Date(sub.submittedAt).toLocaleDateString("en-IN")}
                          </p>
                        </div>
                        <span className={`text-[9px] font-extrabold uppercase tracking-wider px-2 py-0.5 rounded ${sub.status === "reviewed"
                          ? "bg-signal-emerald/10 text-signal-emerald"
                          : "bg-amber-500/10 text-amber-600"}`}>
                          {sub.status === "reviewed" ? "Reviewed" : "Pending Review"}
                        </span>
                      </div>

                      {sub.status === "reviewed" && (
                        <div className="mt-3 space-y-2 text-xs">
                          <div>
                            <span className="text-slate/60 dark:text-paper/40 text-[10px] block">Score:</span>
                            <strong className="text-ink-navy dark:text-paper text-sm font-bold font-mono">{sub.marksAwarded}</strong> / {sub.maxMarks}
                          </div>
                          {sub.remarks && (
                            <p className="text-[10px] text-slate dark:text-paper/85 leading-normal italic py-1 border-l-2 border-line-gray-light dark:border-line-gray-dark pl-2">{sub.remarks}</p>
                          )}
                          {sub.checkedFileUrl && (
                            <a href={sub.checkedFileUrl} target="_blank" rel="noopener noreferrer"
                              className="inline-flex mt-1 py-1.5 px-3 text-center bg-signal-emerald hover:bg-signal-emerald/90 text-white font-bold rounded text-[10px] items-center justify-center gap-1 active:scale-[98] transition-all">
                              📂 Download Evaluated Copy
                            </a>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* WhatsApp Access Modal popup */}
      <AnimatePresence>
        {accessCourseId && activeAccessCourse && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink-navy/60 backdrop-blur-sm"
            onClick={(e) => e.target === e.currentTarget && setAccessCourseId(null)}
            role="dialog" aria-modal="true" aria-labelledby="whatsapp-access-modal-title">
            <motion.div initial={{ scale: 0.96, opacity: 0, y: 15 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.96, opacity: 0, y: 15 }}
              className="bg-paper dark:bg-ink-navy border border-line-gray-light dark:border-line-gray-dark rounded-xl p-6 max-w-sm w-full shadow-lg space-y-5">
              <div className="flex items-start justify-between">
                <div>
                  <h3 id="whatsapp-access-modal-title" className="font-heading font-bold text-base text-ink-navy dark:text-paper">WhatsApp Access</h3>
                  <p className="text-[10px] font-bold text-slate dark:text-paper/50 mt-0.5">{activeAccessCourse.title}</p>
                </div>
                <button onClick={() => setAccessCourseId(null)} aria-label="Close" className="p-1 rounded hover:bg-line-gray-light dark:hover:bg-line-gray-dark transition-colors">
                  <X className="w-4 h-4 text-slate dark:text-paper/60" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="p-4 rounded-lg bg-white dark:bg-line-gray-dark/20 border border-line-gray-light dark:border-line-gray-dark space-y-3">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate dark:text-paper/50 block">Your Access Link</span>

                  {loadingWhatsappLink ? (
                    <p className="text-xs text-slate dark:text-paper/50">Loading your link...</p>
                  ) : whatsappLinkError ? (
                    <p className="text-xs text-alert-coral">{whatsappLinkError} Contact support if this doesn't resolve soon.</p>
                  ) : realWhatsappLink ? (
                    <>
                      <div className="flex items-center justify-between p-2.5 rounded border border-line-gray-light dark:border-line-gray-dark bg-paper dark:bg-ink-navy text-xs">
                        <span className="font-mono text-slate dark:text-paper/85 overflow-hidden truncate select-all">{realWhatsappLink}</span>
                        <button onClick={handleCopyLink} className="ml-2 p-1 hover:bg-line-gray-light dark:hover:bg-line-gray-dark rounded transition-colors text-slate dark:text-paper/60 flex-shrink-0">
                          {copiedLink ? <Check className="w-3.5 h-3.5 text-signal-emerald" /> : <Copy className="w-3.5 h-3.5" />}
                        </button>
                      </div>

                      <a
                        href={realWhatsappLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 text-xs active:scale-[0.98]"
                      >
                        <MessageCircle className="w-4.5 h-4.5" /> Join WhatsApp Group
                      </a>
                    </>
                  ) : null}
                </div>

                <div className="flex gap-2 p-3 rounded bg-amber-500/5 border border-amber-500/15 text-[10px] text-amber-700 dark:text-amber-500 leading-relaxed">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <p>
                    This link is tied to your account batch and must not be shared. Sharing links is a direct violation of our terms and will suspend course access.
                  </p>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>


    </div >
  );
}
