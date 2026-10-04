"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { notFound, useRouter } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AnswerRevealOption, ReviewCard } from "@/components/AnswerReveal";
import {
  ArrowLeft, ArrowRight, Clock, LayoutDashboard, RotateCcw, Trophy,
  SkipForward, AlertCircle, Sun, Moon, Hourglass
} from "lucide-react";
import { useTheme } from "next-themes";
import { useTestGuard } from "@/context/TestGuardContext";
import { QuizLoadingState } from "@/components/QuizLoadingState";
import {
  flattenPaperQuestions,
  computeQuestionOrder,
  reorderFlatQuestionsById,
  type MCQPaper,
  type FlatEntry,
} from "./quizLogic";

interface AttemptStartResponse {
  attemptId: string;
  status: "started" | "resumed";
  questionOrder: string[];
  answers: Record<string, number | null>;
  perQuestionTimes: number[];
  currentIndex: number;
  sectionElapsed: Record<string, number>;
  startedAt: string;
  durationMinutes: number;
  deadlineAt: string;
}

interface QuestionAnalysisEntry {
  questionIndex: number;
  questionId: string;
  status: "correct" | "incorrect" | "skipped";
  userSelected: number | null;
  correctOptionIndex: number;
  marks: number;
  negativeMarks: number;
  marksEarned: number;
  timeTakenSeconds: number;
  explanation: string;
}

interface SubmissionResult {
  submissionId: string;
  score: number;
  totalMarks: number;
  percentage: number;
  isPassed: boolean;
  correctCount: number;
  incorrectCount: number;
  skippedCount: number;
  accuracyPercentage: number;
  totalTimeSeconds: number;
  rank: number;
  totalCompetitors: number;
  percentile: number;
  questionAnalysis: QuestionAnalysisEntry[];
}

interface LeaderboardEntry {
  name: string;
  score: number;
  time: number;
  isUser: boolean;
}

type QuizPhase = "in-progress" | "submitting" | "results" | "result-pending";

export default function QuizPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [paper, setPaper] = useState<MCQPaper | null>(null);
  const [loading, setLoading] = useState(true);
  const [is404, setIs404] = useState(false);
  const [loadError, setLoadError] = useState("");

  const [attempt, setAttempt] = useState<AttemptStartResponse | null>(null);
  const [attemptPhase, setAttemptPhase] = useState<"pending" | "resume-prompt" | "ready">("pending");
  const [attemptError, setAttemptError] = useState("");

  useEffect(() => {
    const fetchQuiz = async () => {
      try {
        const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
        const token = localStorage.getItem("caliber_jwt") || "";
        if (!token) {
          router.push(`/login?next=/quiz/${id}`);
          return;
        }
        const res = await fetch(`${apiURL}/api/quizzes/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 404) { setIs404(true); return; }
        if (res.status === 401) { router.push(`/login?next=/quiz/${id}`); return; }
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          setLoadError(err.detail || "Couldn't load this quiz. Please try again.");
          return;
        }
        const data = await res.json();
        setPaper(data);
      } catch (e) {
        setLoadError("Couldn't load this quiz. Please check your connection and try again.");
      } finally {
        setLoading(false);
      }
    };
    fetchQuiz();
  }, [id, router]);

  // Starts (or resumes) the server-persisted attempt as soon as the paper is
  // known — before QuizEngine ever mounts, so the interactive UI is always
  // initialized from server-confirmed state rather than a blank slate that
  // then has to be reconciled after the fact.
  useEffect(() => {
    if (!paper) return;
    const startAttempt = async () => {
      try {
        const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
        const token = localStorage.getItem("caliber_jwt") || "";
        const order = computeQuestionOrder(paper);
        const res = await fetch(`${apiURL}/api/quizzes/${paper.id}/attempt/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ questionOrder: order }),
        });
        if (!res.ok) {
          // A 403 says why (e.g. a one-attempt Scholarship Test already taken).
          const err = res.status === 403 ? await res.json().catch(() => ({})) : {};
          setAttemptError(err.detail || "Couldn't start this attempt. Please try again.");
          return;
        }
        const data: AttemptStartResponse = await res.json();
        setAttempt(data);
        const alreadyExpired = new Date(data.deadlineAt).getTime() < Date.now();
        // An already-expired resumed attempt skips the prompt entirely —
        // showing "Resume Test" for an attempt that's already over would be
        // misleading. QuizEngine auto-finalizes it on mount instead.
        setAttemptPhase(data.status === "resumed" && !alreadyExpired ? "resume-prompt" : "ready");
      } catch {
        setAttemptError("Couldn't start this attempt. Please check your connection and try again.");
      }
    };
    startAttempt();
  }, [paper]);

  if (is404) return notFound();
  if (loadError) {
    return (
      <div className="pt-32 pb-20 text-center max-w-lg mx-auto">
        <h2 className="text-xl font-bold font-heading mb-4 text-ink-navy dark:text-paper">Couldn&apos;t load this quiz</h2>
        <p className="text-slate dark:text-paper/60 mb-6">{loadError}</p>
        <Link href="/mcq" className="text-sm font-bold text-signal-emerald hover:underline">
          Go back to MCQ Library
        </Link>
      </div>
    );
  }
  if (loading || !paper) return <QuizLoadingState label="Loading quiz engine..." />;

  // Checked here, before QuizEngine (and its hooks) ever mounts — a paper
  // with 0 questions must never reach QuizEngine, since flatQuestions.length
  // drives array sizing for several of QuizEngine's hooks below.
  if (flattenPaperQuestions(paper).length === 0) {
    return (
      <div className="pt-32 pb-20 text-center max-w-lg mx-auto">
        <h2 className="text-xl font-bold font-heading mb-4 text-ink-navy dark:text-paper">No questions available</h2>
        <p className="text-slate dark:text-paper/60 mb-6">This MCQ paper hasn't been populated with questions yet.</p>
        <Link href="/mcq" className="text-sm font-bold text-signal-emerald hover:underline">
          Go back to MCQ Library
        </Link>
      </div>
    );
  }

  if (attemptError) {
    return (
      <div className="pt-32 pb-20 text-center max-w-lg mx-auto">
        <h2 className="text-xl font-bold font-heading mb-4 text-ink-navy dark:text-paper">Couldn&apos;t start this attempt</h2>
        <p className="text-slate dark:text-paper/60 mb-6">{attemptError}</p>
        <Link href="/mcq" className="text-sm font-bold text-signal-emerald hover:underline">
          Go back to MCQ Library
        </Link>
      </div>
    );
  }

  if (attemptPhase === "pending" || !attempt) {
    return <QuizLoadingState label="Preparing your attempt..." />;
  }

  if (attemptPhase === "resume-prompt") {
    return (
      <ResumePrompt
        onResume={() => setAttemptPhase("ready")}
        onExit={() => router.push("/mcq")}
      />
    );
  }

  return <QuizEngine paper={paper} initialAttempt={attempt} />;
}

function ResumePrompt({ onResume, onExit }: { onResume: () => void; onExit: () => void }) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-ink-navy/60 backdrop-blur-sm">
      <motion.div
        initial={{ scale: 0.95, opacity: 0, y: 12 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        className="bg-paper dark:bg-ink-navy border border-line-gray-light dark:border-line-gray-dark rounded-2xl p-6 max-w-sm w-full shadow-xl space-y-4"
      >
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-signal-emerald/10 flex items-center justify-center flex-shrink-0">
            <RotateCcw className="w-5 h-5 text-signal-emerald" />
          </div>
          <div>
            <h3 className="font-heading font-bold text-base text-ink-navy dark:text-paper">Resume Test</h3>
            <p className="text-xs text-slate dark:text-paper/60 mt-1 leading-relaxed">
              We found an unfinished test attempt. Your previous progress has been saved.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={onExit}
            className="flex-1 py-2.5 text-xs font-semibold border border-line-gray-light dark:border-line-gray-dark text-ink-navy dark:text-paper rounded-xl hover:bg-line-gray-light dark:hover:bg-line-gray-dark transition-colors"
          >
            Exit Test
          </button>
          <button
            onClick={onResume}
            className="flex-1 py-2.5 text-xs font-bold bg-signal-emerald text-white rounded-xl hover:bg-signal-emerald/90 transition-colors"
          >
            Resume Test
          </button>
        </div>
      </motion.div>
    </div>
  );
}

// ─── Quiz Engine ──────────────────────────────────────────────────────────
// Precondition: paper has at least one question (enforced by the caller above).
function QuizEngine({ paper, initialAttempt }: { paper: MCQPaper; initialAttempt: AttemptStartResponse }) {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const { setTestActive, guardNavigate } = useTestGuard();
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  // Starts as the attempt the parent already confirmed with the server, but
  // is itself stateful — "Practice Again" (reset, below) starts a genuinely
  // new attempt server-side (the old one is already status:"submitted") and
  // swaps this in, rather than reusing a stale, already-graded attemptId.
  const [activeAttempt, setActiveAttempt] = useState<AttemptStartResponse>(initialAttempt);

  // Reordered to match the active attempt's server-persisted order, so
  // question order never changes mid-attempt and a resumed attempt shows
  // the exact order it started with.
  const flatQuestions = useMemo(() => {
    const base = flattenPaperQuestions(paper);
    return reorderFlatQuestionsById(base, activeAttempt.questionOrder);
  }, [paper, activeAttempt.questionOrder]);
  const total = flatQuestions.length;
  const attemptId = activeAttempt.attemptId;
  const deadlineAtMs = useMemo(() => new Date(activeAttempt.deadlineAt).getTime(), [activeAttempt.deadlineAt]);

  const [phase, setPhase] = useState<QuizPhase>("in-progress");
  const [currentIndex, setCurrentIndex] = useState(() =>
    Math.min(Math.max(initialAttempt.currentIndex || 0, 0), total - 1)
  );

  const [userAnswers, setUserAnswers] = useState<(number | null)[]>(() =>
    flatQuestions.map((e) => (initialAttempt.answers[e.question.id] ?? null))
  );
  const [perQuestionTimes, setPerQuestionTimes] = useState<number[]>(() =>
    initialAttempt.perQuestionTimes.length === total ? initialAttempt.perQuestionTimes : Array(total).fill(0)
  );
  const [elapsedSeconds, setElapsedSeconds] = useState(() =>
    Math.max(0, Math.floor((Date.now() - new Date(initialAttempt.startedAt).getTime()) / 1000))
  );
  const [showFinishWarning, setShowFinishWarning] = useState(false);
  const [submissionResult, setSubmissionResult] = useState<SubmissionResult | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [sectionElapsed, setSectionElapsed] = useState<Record<string, number>>(() => {
    const acc: Record<string, number> = {};
    if (paper.sections) {
      for (const sec of paper.sections) acc[sec.id] = 0;
    }
    return { ...acc, ...initialAttempt.sectionElapsed };
  });

  // Guards the quiz-taking flow while an attempt is actually in progress —
  // stops the moment a submission is in flight, so the results-page
  // navigation that follows a successful finishQuiz() is never blocked.
  useEffect(() => {
    setTestActive(phase === "in-progress");
    return () => setTestActive(false);
  }, [phase, setTestActive]);

  const questionShownAt = useRef<number[]>(Array(total).fill(0));

  useEffect(() => {
    questionShownAt.current[0] = window.performance.now();
  }, []);

  useEffect(() => {
    if (!questionShownAt.current[currentIndex]) {
      questionShownAt.current[currentIndex] = window.performance.now();
    }
  }, [currentIndex]);

  useEffect(() => {
    if (phase !== "in-progress") return;
    const timer = window.setInterval(() => {
      setElapsedSeconds((t) => t + 1);
      const currentSecId = flatQuestions[currentIndex]?.sectionId;
      if (currentSecId) {
        setSectionElapsed(prev => ({
          ...prev,
          [currentSecId]: (prev[currentSecId] || 0) + 1
        }));
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [phase, currentIndex, flatQuestions]);

  useEffect(() => {
    if (phase !== "in-progress") return;
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [phase]);

  // Keeps a ref to the latest finishQuiz closure so the long-lived autosave
  // callback below (stable across renders) can trigger a real submission on
  // expiry without capturing a stale closure from an earlier render.
  const finishQuizRef = useRef<() => void>(() => {});

  // Latest-value snapshot for autosave, read at call-time instead of being a
  // dependency of the debounce/heartbeat effects below — otherwise those
  // effects would re-fire every second just because the 1s timer tick
  // updates elapsedSeconds/sectionElapsed, defeating the debounce entirely.
  const latestSnapshotRef = useRef({ userAnswers, perQuestionTimes, currentIndex, sectionElapsed, elapsedSeconds });
  useEffect(() => {
    latestSnapshotRef.current = { userAnswers, perQuestionTimes, currentIndex, sectionElapsed, elapsedSeconds };
  }, [userAnswers, perQuestionTimes, currentIndex, sectionElapsed, elapsedSeconds]);

  const attemptExpiredRef = useRef(false);

  const saveProgressNow = useCallback(async () => {
    if (attemptExpiredRef.current) return;
    const snap = latestSnapshotRef.current;
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt");
      if (!token) return;
      const res = await fetch(`${apiURL}/api/quizzes/${paper.id}/attempt/${attemptId}/progress`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          answers: Object.fromEntries(flatQuestions.map((e, i) => [e.question.id, snap.userAnswers[i]])),
          perQuestionTimes: snap.perQuestionTimes,
          currentIndex: snap.currentIndex,
          sectionElapsed: snap.sectionElapsed,
          elapsedSeconds: snap.elapsedSeconds,
        }),
      });
      const data = await res.json().catch(() => null);
      if (data && data.success === false && data.status === "expired" && !attemptExpiredRef.current) {
        attemptExpiredRef.current = true;
        finishQuizRef.current();
      }
    } catch {
      // Best-effort — a failed autosave doesn't interrupt the attempt; the
      // final submit-v2 call (with the server-persisted attempt) is still
      // the real source of truth.
    }
  }, [paper.id, attemptId, flatQuestions]);

  // Debounced autosave on every answer/navigation change.
  useEffect(() => {
    if (phase !== "in-progress") return;
    const t = window.setTimeout(() => { saveProgressNow(); }, 800);
    return () => window.clearTimeout(t);
  }, [userAnswers, currentIndex, phase, saveProgressNow]);

  // Heartbeat so idle reading time / section-time still gets persisted, and
  // so an expired deadline is detected within ~20s even without an answer
  // change to trigger the debounced save above.
  useEffect(() => {
    if (phase !== "in-progress") return;
    const interval = window.setInterval(() => { saveProgressNow(); }, 20000);
    return () => window.clearInterval(interval);
  }, [phase, saveProgressNow]);

  // If this attempt was already past its deadline the moment it was
  // resumed (the student was away longer than the test's duration),
  // finalize it immediately instead of letting them interact with an
  // attempt that's already over.
  useEffect(() => {
    if (Date.now() > deadlineAtMs) {
      attemptExpiredRef.current = true;
      finishQuizRef.current();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentEntry = flatQuestions[currentIndex];
  const currentQ = currentEntry.question;
  const currentCase = currentEntry.question.case_narrative;
  // Stable cluster identity for the narrative panel's remount key — prefers
  // the real case_group_id so the panel never remounts while navigating
  // within one case, even in the (pre-migration) edge case where narrative
  // text is empty or happens to collide between two different case blocks.
  const currentCaseKey = currentEntry.question.case_group_id || currentCase;
  const selectedOption = userAnswers[currentIndex];
  const answeredCount = userAnswers.filter((a) => a !== null).length;
  const skippedCount = total - answeredCount;

  function selectOption(optionIndex: number, answeredAt: number) {
    const alreadyAnswered = userAnswers[currentIndex] !== null;
    const duration = alreadyAnswered
      ? perQuestionTimes[currentIndex]
      : Math.max(1, Math.round((answeredAt - questionShownAt.current[currentIndex]) / 1000));
    setUserAnswers((prev) => prev.map((a, i) => (i === currentIndex ? optionIndex : a)));
    setPerQuestionTimes((prev) => prev.map((t, i) => (i === currentIndex ? duration : t)));
  }

  function clearAnswer() {
    setUserAnswers((prev) => prev.map((a, i) => (i === currentIndex ? null : a)));
  }

  function goBack() {
    if (currentIndex > 0) setCurrentIndex((i) => i - 1);
  }

  function goNext() {
    if (currentIndex < total - 1) setCurrentIndex((i) => i + 1);
  }

  function skipQuestion() {
    if (currentIndex < total - 1) setCurrentIndex((i) => i + 1);
  }

  function jumpTo(index: number) {
    setCurrentIndex(index);
  }

  function tryFinish() {
    if (skippedCount > 0) {
      setShowFinishWarning(true);
    } else {
      finishQuiz();
    }
  }

  async function finishQuiz() {
    setShowFinishWarning(false);
    setSubmitError(null);
    setPhase("submitting");
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt");
      if (!token) {
        setSubmitError("You've been signed out. Please log in again to submit this attempt.");
        setPhase("in-progress");
        return;
      }
      const res = await fetch(`${apiURL}/api/quizzes/${paper.id}/submit-v2`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          // Question-ID-keyed, not positional — the server independently
          // fetches and canonically orders questions, so a plain index into
          // this client's (possibly shuffled) flatQuestions would grade the
          // wrong question whenever shuffleQuestions is enabled.
          answers: Object.fromEntries(flatQuestions.map((e, i) => [e.question.id, userAnswers[i]])),
          perQuestionTimes: perQuestionTimes,
          elapsedSeconds: elapsedSeconds,
          // Links this submission to the persisted attempt row — the server
          // uses it to reject a second submission of the same attempt
          // (returning the original result instead) and, if this call
          // arrives after the attempt's real deadline, to grade the last
          // autosaved answers rather than whatever was just posted.
          attemptId,
        })
      });
      if (!res.ok) {
        throw new Error("Server rejected the submission");
      }
      const data = await res.json();
      // Scholarship Test: marks and rank stay hidden until results are published.
      if (data.resultPending) {
        setPhase("result-pending");
        return;
      }
      setSubmissionResult(data as SubmissionResult);
      setPhase("results");

      // Best-effort — the results view works fine without it, just shows
      // no leaderboard/topper comparison if this fails.
      try {
        const lbRes = await fetch(`${apiURL}/api/quizzes/${paper.id}/leaderboard`, {
          headers: { "Authorization": `Bearer ${token}` },
        });
        if (lbRes.ok) setLeaderboard(await lbRes.json());
      } catch { /* leaderboard is optional */ }
    } catch (e) {
      console.warn("Failed to submit quiz attempt", e);
      setSubmitError("Couldn't submit your attempt — check your connection and try again. Your answers are still saved.");
      setPhase("in-progress");
    }
  }
  finishQuizRef.current = finishQuiz;

  const reset = useCallback(async () => {
    // "Practice Again" must start a genuinely new server-side attempt — the
    // previous one is already status:"submitted", so reusing its attemptId
    // would make the next submit-v2 call hit the idempotent-replay branch
    // and just return the OLD result again instead of grading the new one.
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";
      const order = computeQuestionOrder(paper);
      const res = await fetch(`${apiURL}/api/quizzes/${paper.id}/attempt/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ questionOrder: order }),
      });
      if (res.ok) {
        const data: AttemptStartResponse = await res.json();
        setActiveAttempt(data);
      }
    } catch {
      // If this fails, local UI state still resets below so the user isn't
      // stuck — the next autosave/submit call will simply surface the usual
      // "check your connection" messaging rather than silently misgrading.
    }
    attemptExpiredRef.current = false;
    setPhase("in-progress");
    setCurrentIndex(0);
    setUserAnswers(Array(total).fill(null));
    setPerQuestionTimes(Array(total).fill(0));
    setElapsedSeconds(0);
    setSectionElapsed(() => {
      const acc: Record<string, number> = {};
      if (paper.sections) {
        for (const sec of paper.sections) acc[sec.id] = 0;
      }
      return acc;
    });
    setShowFinishWarning(false);
    setSubmissionResult(null);
    setLeaderboard([]);
    setSubmitError(null);
    questionShownAt.current = [window.performance.now(), ...Array(total - 1).fill(0)];
  }, [total, paper]);

  if (phase === "results" && submissionResult) {
    return (
      <ResultsView
        paper={paper}
        flatQuestions={flatQuestions}
        result={submissionResult}
        leaderboard={leaderboard}
        perQuestionTimes={perQuestionTimes}
        onReset={reset}
      />
    );
  }

  if (phase === "submitting") {
    return <QuizLoadingState label="Submitting your attempt..." />;
  }

  if (phase === "result-pending") {
    return (
      <div className="pt-32 pb-20 px-4 text-center max-w-lg mx-auto">
        <div className="w-14 h-14 mx-auto mb-5 rounded-2xl bg-amber-400/15 text-amber-500 flex items-center justify-center">
          <Hourglass className="w-7 h-7" />
        </div>
        <h2 className="text-2xl font-extrabold font-heading mb-3 text-ink-navy dark:text-paper">Your test is submitted</h2>
        <p className="text-slate dark:text-paper/70 mb-2">Your result will come soon.</p>
        <p className="text-sm text-slate dark:text-paper/60 mb-8">
          Once it&apos;s out, you can see your rank, marks and answers in your dashboard.
        </p>
        <Link href="/dashboard?tab=results"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy text-sm font-bold hover:opacity-90 transition-opacity">
          <LayoutDashboard className="w-4 h-4" /> Go to dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="pt-16 min-h-screen flex flex-col bg-line-gray-light/20 dark:bg-line-gray-dark/10">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex-1 w-full max-w-[1500px] mx-auto px-4 sm:px-6 py-8 flex flex-col"
      >
        <div className="w-full max-w-7xl mx-auto space-y-4 mb-8">
          <div className="flex gap-2 p-1 bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark rounded-xl overflow-x-auto whitespace-nowrap " style={{ scrollbarWidth: "none" }}>
            {paper.sections?.map(sec => (
              <button
                key={sec.id}
                onClick={() => {
                  const firstIdx = flatQuestions.findIndex(q => q.sectionId === sec.id);
                  if (firstIdx !== -1) jumpTo(firstIdx);
                }}
                className={`px-4 py-2 text-xs font-bold rounded-lg transition-all ${currentEntry.sectionId === sec.id ? 'bg-signal-emerald text-white shadow-sm' : 'text-slate dark:text-paper/60 hover:bg-line-gray-light/60 dark:hover:bg-line-gray-dark'}`}
              >
                {sec.title}
              </button>
            ))}
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <button
                onClick={() => guardNavigate("/mcq")}
                className="flex items-center gap-1.5 text-xs text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper transition-colors bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark px-4 py-2 rounded-xl shadow-sm"
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Exit
              </button>
              {mounted && (
                <button
                  onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
                  className="p-2 rounded-xl bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark text-slate dark:text-paper/70 hover:bg-line-gray-light dark:hover:bg-line-gray-dark transition-all shadow-sm flex items-center justify-center gap-2 text-[10px] font-bold"
                  title="Toggle Light/Dark Mode"
                >
                  {resolvedTheme === "dark" ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-500" />}
                  {resolvedTheme === "dark" ? "Light Mode" : "Dark Mode"}
                </button>
              )}
            </div>

            <div className="flex gap-6 sm:gap-8 bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark px-6 py-2 rounded-xl shadow-sm">
              <div className="flex flex-col items-center">
                <span className="text-[9px] font-bold text-slate dark:text-paper/40 uppercase tracking-widest mb-0.5">Total Time</span>
                <div className="flex items-center gap-1.5 font-mono text-base font-extrabold text-ink-navy dark:text-paper">
                  <Clock className="w-3.5 h-3.5 text-signal-emerald" />
                  {formatTime(elapsedSeconds)}
                </div>
              </div>
              <div className="flex flex-col items-center pl-6 sm:pl-8 border-l border-line-gray-light dark:border-line-gray-dark">
                <span className="text-[9px] font-bold text-slate dark:text-paper/40 uppercase tracking-widest mb-0.5">Section Time</span>
                <div className="flex items-center gap-1.5 font-mono text-base font-bold text-ink-navy/80 dark:text-paper/80">
                  <Clock className="w-3.5 h-3.5 text-slate" />
                  {formatTime(sectionElapsed[currentEntry.sectionId] || 0)}
                </div>
              </div>
            </div>

            <span className="font-mono text-xs font-bold bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy px-3 py-1.5 rounded-lg shadow-sm">
              {answeredCount}/{total} <span className="font-sans font-normal opacity-70 ml-1">answered</span>
            </span>
          </div>

          <div className="w-full h-1.5 bg-line-gray-light dark:bg-line-gray-dark rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-signal-emerald rounded-full"
              animate={{ width: `${(answeredCount / total) * 100}%` }}
            />
          </div>

          {submitError && (
            <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-alert-coral/10 border border-alert-coral/30 text-alert-coral text-xs font-semibold">
              <AlertCircle className="w-4 h-4 shrink-0" /> {submitError}
            </div>
          )}
        </div>

        <div className="grid lg:grid-cols-12 gap-6 items-start max-w-7xl mx-auto w-full">
          {currentCase && (
            <div className="lg:col-span-5 space-y-4">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate dark:text-paper/40">
                {currentEntry.sectionTitle}
              </p>
              <div className="bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark rounded-2xl overflow-hidden shadow-lg lg:min-h-[400px]">
                {/* Keyed on the case's own text, not currentIndex — this stays
                    the same DOM node (no remount/re-animate) across every
                    sub-question of the same case, and only actually animates
                    when the case itself changes. */}
                <AnimatePresence mode="wait">
                  <motion.div
                    key={`case-${currentCaseKey}`}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="p-6"
                  >
                    <p className="text-[10px] font-bold uppercase tracking-widest text-slate dark:text-paper/40 mb-3">Case Study / Passage</p>
                    <div className="text-sm text-ink-navy dark:text-paper leading-relaxed whitespace-pre-wrap">
                      {currentCase}
                    </div>
                  </motion.div>
                </AnimatePresence>
              </div>
            </div>
          )}

          <div className={`${currentCase ? "lg:col-span-4" : "lg:col-span-9"} flex flex-col h-full space-y-4`}>
            <AnimatePresence mode="wait">
              <motion.div
                key={`opts-${currentIndex}`}
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.98 }}
                className="bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark rounded-2xl overflow-hidden shadow-lg flex flex-col lg:min-h-[400px]"
              >
                <div className="p-6 flex-1 space-y-3">
                  {!currentCase && (
                    <p className="text-[10px] font-semibold uppercase tracking-widest text-slate dark:text-paper/40 mb-1">
                      {currentEntry.sectionTitle}
                    </p>
                  )}
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-xs font-mono text-slate dark:text-paper/50 uppercase tracking-widest">
                      Question {currentIndex + 1} of {total}
                    </p>
                    <div className="flex gap-2">
                      <span className="text-[10px] font-bold bg-signal-emerald/10 text-signal-emerald px-2 py-0.5 rounded">
                        +{currentQ.marks || 1} Marks
                      </span>
                      {(currentQ.negativeMarks || 0) > 0 && (
                        <span className="text-[10px] font-bold bg-alert-coral/10 text-alert-coral px-2 py-0.5 rounded">
                          -{(currentQ.negativeMarks || 0)} Marks
                        </span>
                      )}
                    </div>
                  </div>
                  <p className="text-base font-medium text-ink-navy dark:text-paper leading-relaxed whitespace-pre-wrap mb-4 pb-4 border-b border-line-gray-light dark:border-line-gray-dark">
                    {currentQ.text}
                  </p>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-slate dark:text-paper/40 mb-1">Select an Option</p>
                  {currentQ.options.map((option, index) => (
                    <AnswerRevealOption
                      key={index}
                      label={String.fromCharCode(65 + index)}
                      text={option}
                      state={index === selectedOption ? "selected" : "idle"}
                      onClick={(event) => selectOption(index, event.timeStamp)}
                      disabled={false}
                    />
                  ))}
                </div>

                <div className="p-6 pt-0 border-t border-line-gray-light dark:border-line-gray-dark bg-line-gray-light/10 dark:bg-line-gray-dark/10">
                  {selectedOption !== null && (
                    <div className="flex items-center gap-2 mb-4 pt-4">
                      <p className="text-[10px] text-slate dark:text-paper/40 flex-1">
                        Changed your mind?
                      </p>
                      <button
                        onClick={clearAnswer}
                        className="text-[10px] font-semibold text-slate dark:text-paper/50 hover:text-alert-coral transition-colors px-2 py-1 rounded-lg hover:bg-alert-coral/10"
                      >
                        Clear Answer
                      </button>
                    </div>
                  )}

                  <div className="grid grid-cols-3 gap-2 mt-4">
                    <button
                      onClick={goBack}
                      disabled={currentIndex === 0}
                      className="flex items-center justify-center gap-1.5 py-2.5 border border-line-gray-light dark:border-line-gray-dark text-ink-navy dark:text-paper text-xs font-semibold rounded-xl hover:bg-line-gray-light/40 dark:hover:bg-line-gray-dark/40 active:scale-[0.98] transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      <ArrowLeft className="w-3.5 h-3.5" /> Back
                    </button>

                    {selectedOption === null && currentIndex < total - 1 ? (
                      <button
                        onClick={skipQuestion}
                        className="flex items-center justify-center gap-1.5 py-2.5 border border-dashed border-slate/30 dark:border-paper/20 text-slate dark:text-paper/50 text-xs font-semibold rounded-xl hover:border-slate hover:text-ink-navy dark:hover:text-paper active:scale-[0.98] transition-all"
                      >
                        <SkipForward className="w-3.5 h-3.5" /> Skip
                      </button>
                    ) : (
                      <div />
                    )}

                    {currentIndex < total - 1 ? (
                      <button
                        onClick={goNext}
                        className="flex items-center justify-center gap-1.5 py-2.5 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy text-xs font-bold rounded-xl hover:opacity-90 active:scale-[0.98] transition-all"
                      >
                        Next <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    ) : (
                      <button
                        onClick={tryFinish}
                        className="flex items-center justify-center gap-1.5 py-2.5 bg-signal-emerald text-white text-xs font-bold rounded-xl hover:bg-signal-emerald/90 active:scale-[0.98] transition-all"
                      >
                        <Trophy className="w-3.5 h-3.5" /> Finish
                      </button>
                    )}
                  </div>
                </div>
              </motion.div>
            </AnimatePresence>
          </div>

          <div className="lg:col-span-3">
            <div className="bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark rounded-2xl p-5 shadow-lg lg:sticky lg:top-24">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate dark:text-paper/40 mb-4">
                Question Navigator
              </p>
              <div className="grid grid-cols-5 sm:grid-cols-8 lg:grid-cols-5 gap-2" aria-label="Question navigator">
                {flatQuestions.map((_, index) => {
                  const qSectionId = flatQuestions[index].sectionId;
                  if (qSectionId !== currentEntry.sectionId) return null;

                  return (
                    <button
                      key={index}
                      onClick={() => jumpTo(index)}
                      title={`Q${index + 1}${userAnswers[index] !== null ? " (answered)" : " (unanswered)"}`}
                      className={`aspect-square flex items-center justify-center rounded-lg text-xs font-bold transition-all ${index === currentIndex
                        ? "bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy ring-2 ring-ink-navy/20 dark:ring-paper/20 shadow-sm"
                        : userAnswers[index] !== null
                          ? "bg-signal-emerald/10 text-signal-emerald border border-signal-emerald/20 hover:bg-signal-emerald/20"
                          : "bg-line-gray-light/50 dark:bg-line-gray-dark text-slate/60 dark:text-paper/50 hover:bg-line-gray-light dark:hover:bg-line-gray-dark/80"
                        }`}
                    >
                      {index + 1}
                    </button>
                  );
                })}
              </div>

              <div className="mt-6 space-y-2 text-[10px] text-slate dark:text-paper/60">
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-signal-emerald/10 border border-signal-emerald/20 block" /> Answered
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-ink-navy dark:bg-paper block" /> Current Status
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-line-gray-light/50 dark:bg-line-gray-dark block" /> Unanswered
                </div>
              </div>

              <div className="mt-8 pt-4 border-t border-line-gray-light dark:border-line-gray-dark">
                <p className="text-center text-[10px] text-slate dark:text-paper/40 bg-line-gray-light/30 dark:bg-line-gray-dark/30 p-2 rounded-lg">
                  Submit test anytime. Unanswered questions score 0 — only wrong answers lose marks.
                </p>
              </div>
            </div>
          </div>

        </div>
      </motion.div>

      <AnimatePresence>
        {showFinishWarning && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink-navy/60 backdrop-blur-sm"
            onClick={(e) => e.target === e.currentTarget && setShowFinishWarning(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0, y: 12 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.95, opacity: 0, y: 12 }}
              className="bg-paper dark:bg-ink-navy border border-line-gray-light dark:border-line-gray-dark rounded-2xl p-6 max-w-sm w-full shadow-xl space-y-4"
            >
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-xl bg-amber-500/10 flex items-center justify-center flex-shrink-0">
                  <AlertCircle className="w-5 h-5 text-amber-500" />
                </div>
                <div>
                  <h3 className="font-heading font-bold text-base text-ink-navy dark:text-paper">
                    {skippedCount} unanswered question{skippedCount !== 1 ? "s" : ""}
                  </h3>
                  <p className="text-xs text-slate dark:text-paper/60 mt-1 leading-relaxed">
                    You have skipped {skippedCount} question{skippedCount !== 1 ? "s" : ""}. Skipped questions score 0 (no negative marks). You can go back and answer them, or submit now.
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setShowFinishWarning(false)}
                  className="flex-1 py-2.5 text-xs font-semibold border border-line-gray-light dark:border-line-gray-dark text-ink-navy dark:text-paper rounded-xl hover:bg-line-gray-light dark:hover:bg-line-gray-dark transition-colors"
                >
                  Review answers
                </button>
                <button
                  onClick={finishQuiz}
                  className="flex-1 py-2.5 text-xs font-bold bg-signal-emerald text-white rounded-xl hover:bg-signal-emerald/90 transition-colors"
                >
                  Submit anyway
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function formatTime(seconds: number) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function ResultsView({
  paper, flatQuestions, result, leaderboard, perQuestionTimes, onReset,
}: {
  paper: MCQPaper;
  flatQuestions: FlatEntry[];
  result: SubmissionResult;
  leaderboard: LeaderboardEntry[];
  perQuestionTimes: number[];
  onReset: () => void;
}) {
  const total = flatQuestions.length;
  // Keyed by question ID, not array position — the backend returns
  // questionAnalysis sorted by its own canonical order_index order, which
  // does not necessarily match this client's (possibly shuffled) flatQuestions
  // order, so a positional analysis[i] lookup could show the wrong question's
  // correct/incorrect status.
  const analysisById = new Map(result.questionAnalysis.map((a) => [a.questionId, a]));
  const score = result.score;
  const actualTotalMarks = result.totalMarks;
  const accuracy = Math.round(result.accuracyPercentage);
  const elapsedSeconds = result.totalTimeSeconds;

  // Real top scorer from the actual leaderboard — undefined if this is the
  // first attempt on this paper (nothing to compare against yet), in which
  // case comparison UI is hidden rather than showing invented numbers.
  const topper = leaderboard.length > 0 ? leaderboard[0] : null;

  const scoreChartData = topper
    ? [{ name: "Score", You: score, Topper: topper.score }]
    : [{ name: "Score", You: score }];

  const timeChartData = flatQuestions.map((entry, i) => ({
    question: `Q${i + 1}`,
    You: perQuestionTimes[i],
  }));

  const sectionStats = (paper.sections || []).map((section) => {
    const indices = flatQuestions
      .map((e, i) => (e.sectionId === section.id ? i : -1))
      .filter((i) => i >= 0);
    const correct = indices.filter((i) => analysisById.get(flatQuestions[i].question.id)?.status === "correct").length;
    return {
      section: section.title.replace(/^Section [A-Z] — /, ""),
      fullTitle: section.title,
      Accuracy: indices.length ? Math.round((correct / indices.length) * 100) : 0,
      correct,
      total: indices.length,
    };
  });

  const headline = [
    { label: "Score", value: `${score}/${actualTotalMarks}` },
    { label: "Accuracy", value: `${accuracy}%` },
    { label: "Time taken", value: formatTime(elapsedSeconds) },
    { label: "Rank", value: result.totalCompetitors > 0 ? `#${result.rank} of ${result.totalCompetitors}` : "—" },
    { label: "Percentile", value: result.totalCompetitors > 0 ? `Top ${(100 - result.percentile).toFixed(0)}%` : "—" },
  ];

  // Real attempts only — server already sorts by score desc, time asc.
  const sortedLeaderboard = leaderboard.slice(0, 10);

  const RankBadge = ({ rank }: { rank: number }) => {
    const bg =
      rank === 1 ? "bg-amber-100 dark:bg-amber-955/35 text-amber-700 dark:text-amber-400 border-amber-300 dark:border-amber-800/40" :
        rank === 2 ? "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-400 border-slate-300 dark:border-slate-700" :
          rank === 3 ? "bg-orange-100 dark:bg-orange-955/30 text-orange-700 dark:text-orange-400 border-orange-200 dark:border-orange-850" :
            "bg-line-gray-light/60 dark:bg-line-gray-dark text-slate dark:text-paper/40 border-line-gray-light dark:border-line-gray-dark/50";

    return (
      <span className={`w-6 h-6 rounded-full border flex items-center justify-center text-[10px] font-bold font-mono ${bg}`}>
        {rank}
      </span>
    );
  };

  return (
    <motion.main
      initial={{ opacity: 0, x: 30 }}
      animate={{ opacity: 1, x: 0 }}
      className="pt-16 max-w-5xl mx-auto px-4 sm:px-6 py-10 space-y-8"
    >
      <section className="bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark rounded-2xl p-6 sm:p-8">
        <p className="font-mono text-xs text-slate dark:text-paper/50 uppercase tracking-widest">Complete · {paper.title}</p>
        <h1 className="font-heading font-extrabold text-3xl text-ink-navy dark:text-paper mt-2">Your analysis</h1>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-6">
          {headline.map(({ label, value }) => (
            <div key={label} className="p-3 rounded-xl bg-line-gray-light/45 dark:bg-ink-navy/30">
              <p className="font-mono font-bold text-xl text-ink-navy dark:text-paper">{value}</p>
              <p className="text-[11px] text-slate dark:text-paper/55 mt-1">{label}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="grid lg:grid-cols-2 gap-6">
        <ChartCard title={topper ? "Score comparison — You vs Topper" : "Your score"}>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={scoreChartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.08} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} domain={[0, actualTotalMarks || 1]} />
              <Tooltip />
              <Legend />
              <Bar dataKey="You" fill="#16a365" radius={[6, 6, 0, 0]} />
              {topper && <Bar dataKey="Topper" fill="#64748b" radius={[6, 6, 0, 0]} />}
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <section className="bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark rounded-2xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-heading font-bold text-base text-ink-navy dark:text-paper flex items-center gap-1.5">
                <Trophy className="w-4 h-4 text-yellow-500" /> Leaderboard — Top Performers
              </h2>
              <span className="text-[9px] px-2 py-0.5 rounded bg-line-gray-light dark:bg-line-gray-dark text-slate dark:text-paper/50 font-bold uppercase tracking-wider">
                Live Rankings
              </span>
            </div>

            <div className="space-y-2">
              {sortedLeaderboard.length === 0 && (
                <p className="text-xs text-slate dark:text-paper/50 text-center py-4">
                  You're the first to attempt this paper — rankings will fill in as more students take it.
                </p>
              )}
              {sortedLeaderboard.map((item, idx) => {
                const rank = idx + 1;
                return (
                  <motion.div
                    key={`${item.name}-${idx}`}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.05 }}
                    className={`flex items-center justify-between p-2.5 rounded-xl border transition-all ${item.isUser
                      ? "bg-signal-emerald/5 dark:bg-signal-emerald/10 border-signal-emerald/30 shadow-sm"
                      : "bg-paper/40 dark:bg-line-gray-dark/10 border-line-gray-light dark:border-line-gray-dark/30"
                      }`}
                  >
                    <div className="flex items-center gap-3">
                      <RankBadge rank={rank} />
                      <div>
                        <p className={`text-xs font-semibold ${item.isUser ? "text-signal-emerald dark:text-emerald-400 font-bold" : "text-ink-navy dark:text-paper"}`}>
                          {item.name} {item.isUser && "(You)"}
                        </p>
                        <p className="text-[9px] text-slate dark:text-paper/40 font-mono mt-0.5">
                          Time: {formatTime(item.time)}
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <span className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full ${item.isUser
                        ? "bg-signal-emerald/10 text-signal-emerald dark:text-emerald-400"
                        : "bg-line-gray-light/50 dark:bg-line-gray-dark/60 text-slate dark:text-paper/50"
                        }`}>
                        {item.score} Marks
                      </span>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </div>
        </section>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <ChartCard title="Section-wise accuracy (%)">
          <ResponsiveContainer width="100%" height={245}>
            <BarChart data={sectionStats} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.08} />
              <XAxis dataKey="section" tick={{ fontSize: 10 }} interval={0} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(value, _name, props) =>
                  [`${value}% (${props.payload.correct}/${props.payload.total})`, "Accuracy"]
                }
                labelFormatter={(label) =>
                  sectionStats.find((s) => s.section === label)?.fullTitle ?? label
                }
              />
              <Bar dataKey="Accuracy" fill="#16a365" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Time per question (seconds)">
          <ResponsiveContainer width="100%" height={245}>
            <BarChart data={timeChartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.08} />
              <XAxis dataKey="question" tick={{ fontSize: 9 }} interval={Math.floor(total / 10)} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="You" fill="#16a365" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <section>
        <h2 className="font-heading font-bold text-xl text-ink-navy dark:text-paper mb-4">Full question review</h2>
        <div className="space-y-4">
          {flatQuestions.map((entry, index) => (
            <div key={entry.question.id}>
              {(index === 0 || entry.sectionId !== flatQuestions[index - 1].sectionId) && (
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate dark:text-paper/40 mb-2 mt-4">
                  {entry.sectionTitle}
                </p>
              )}
              {entry.question.case_narrative && (
                <div className="bg-slate/5 border-l-2 border-slate/20 p-3 mb-2 rounded-r-lg text-sm italic">
                  {entry.question.case_narrative}
                </div>
              )}
              <ReviewCard
                index={index}
                questionText={entry.question.text}
                options={entry.question.options}
                userAnswerIndex={analysisById.get(entry.question.id)?.userSelected ?? null}
                correctAnswerIndex={analysisById.get(entry.question.id)?.correctOptionIndex ?? -1}
                explanation={analysisById.get(entry.question.id)?.explanation || ""}
                timeTakenSeconds={perQuestionTimes[index]}
              />
            </div>
          ))}
        </div>
      </section>

      <div className="flex flex-col sm:flex-row gap-3 pb-4">
        <button
          onClick={onReset}
          className="flex-1 flex justify-center items-center gap-2 py-3 border-2 border-ink-navy dark:border-paper text-ink-navy dark:text-paper font-bold rounded-xl hover:opacity-90 active:scale-[0.98] transition-all cursor-pointer"
        >
          <RotateCcw className="w-4 h-4" /> Practice Again
        </button>
        <Link
          href="/mcq"
          className="flex-1 flex justify-center items-center gap-2 py-3 bg-signal-emerald text-white font-bold rounded-xl hover:opacity-90 active:scale-[0.98] transition-all"
        >
          <LayoutDashboard className="w-4 h-4" /> Back to MCQs
        </Link>
      </div>
    </motion.main>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white dark:bg-line-gray-dark/40 border border-line-gray-light dark:border-line-gray-dark rounded-2xl p-5">
      <h2 className="font-heading font-bold text-base text-ink-navy dark:text-paper mb-3">{title}</h2>
      {children}
    </section>
  );
}
