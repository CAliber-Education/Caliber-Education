"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, Award, Check, Clock, Hourglass, Minus, Trophy, X } from "lucide-react";
import { formatDuration, formatMarks, type ScholarshipQuestionResult, type ScholarshipResult } from "@/lib/scholarship";

type Filter = "all" | "correct" | "incorrect" | "skipped";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "correct", label: "Correct" },
  { id: "incorrect", label: "Wrong" },
  { id: "skipped", label: "Not answered" },
];

export default function ScholarshipResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [result, setResult] = useState<ScholarshipResult | null>(null);
  const [error, setError] = useState<{ pending: boolean; message: string } | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    const token = localStorage.getItem("caliber_jwt");
    if (!token) {
      router.push(`/login?next=/scholarship/${id}/result`);
      return;
    }
    fetch(`${process.env.NEXT_PUBLIC_API_URL || ""}/api/scholarship-tests/${id}/my-result`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (res.status === 401) { router.push(`/login?next=/scholarship/${id}/result`); return; }
        const data = await res.json().catch(() => ({}));
        if (res.ok) setResult(data);
        else setError({ pending: res.status === 403, message: data.detail || "Couldn't load your result. Please try again." });
      })
      .catch(() => setError({ pending: false, message: "Couldn't load your result. Please check your connection and try again." }));
  }, [id, router]);

  const shown = useMemo(
    () => (result?.questions ?? []).map((q, i) => ({ q, n: i + 1 })).filter(({ q }) => filter === "all" || q.status === filter),
    [result, filter],
  );

  if (error) {
    return (
      <div className="pt-32 pb-20 px-4 text-center max-w-lg mx-auto">
        {error.pending && (
          <div className="w-14 h-14 mx-auto mb-5 rounded-2xl bg-amber-400/15 text-amber-500 flex items-center justify-center">
            <Hourglass className="w-7 h-7" />
          </div>
        )}
        <h2 className="text-xl font-bold font-heading mb-3 text-ink-navy dark:text-paper">
          {error.pending ? "Result coming soon" : "Result not available"}
        </h2>
        <p className="text-slate dark:text-paper/60 mb-6">{error.message}</p>
        <Link href="/dashboard?tab=results" className="text-sm font-bold text-signal-emerald hover:underline">Back to dashboard</Link>
      </div>
    );
  }

  if (!result) {
    return <div className="pt-32 text-center text-slate dark:text-paper/60">Loading your result…</div>;
  }

  const counts: Record<Filter, number> = {
    all: result.questions.length,
    correct: result.correctCount,
    incorrect: result.incorrectCount,
    skipped: result.skippedCount,
  };

  return (
    <div className="pt-16 min-h-screen bg-paper dark:bg-ink-navy">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-10">
        <Link href="/dashboard?tab=results" className="inline-flex items-center gap-1.5 text-xs font-bold text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper mb-6">
          <ArrowLeft className="w-3.5 h-3.5" /> Dashboard
        </Link>

        <header className="mb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-700 dark:text-amber-300 text-xs font-bold mb-3">
            <Award className="w-3.5 h-3.5" /> Result analysis
          </div>
          <h1 className="font-heading font-extrabold text-2xl sm:text-3xl text-ink-navy dark:text-paper">{result.title}</h1>
        </header>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-10">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            className="col-span-2 sm:col-span-1 rounded-2xl border border-amber-500/40 bg-gradient-to-br from-amber-400/20 to-amber-500/5 p-5">
            <p className="text-[11px] font-bold uppercase tracking-wider text-amber-700 dark:text-amber-300 flex items-center gap-1.5">
              <Trophy className="w-3.5 h-3.5" /> Your rank
            </p>
            <p className="mt-1 font-heading font-black text-4xl text-ink-navy dark:text-paper">{result.rank}</p>
          </motion.div>
          <Stat label="Marks" value={`${formatMarks(result.score)} / ${formatMarks(result.totalMarks)}`} />
          <Stat label="Correct · Wrong" value={`${result.correctCount} · ${result.incorrectCount}`} />
          <Stat label="Time taken" value={formatDuration(result.timeSeconds)} icon={<Clock className="w-3.5 h-3.5" />} />
        </div>

        <section>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h2 className="font-heading font-bold text-lg text-ink-navy dark:text-paper">Your answers</h2>
            <div className="flex flex-wrap gap-1.5">
              {FILTERS.map((f) => (
                <button key={f.id} type="button" onClick={() => setFilter(f.id)}
                  className={`px-3 py-1.5 rounded-full text-xs font-bold border transition-colors ${filter === f.id
                    ? "bg-ink-navy text-paper border-ink-navy dark:bg-paper dark:text-ink-navy dark:border-paper"
                    : "border-line-gray-light dark:border-line-gray-dark text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper"}`}>
                  {f.label} ({counts[f.id]})
                </button>
              ))}
            </div>
          </div>
          {shown.length === 0 ? (
            <p className="text-sm text-slate dark:text-paper/60 py-8 text-center">No questions here.</p>
          ) : (
            <div className="space-y-4">
              {shown.map(({ q, n }) => <QuestionCard key={q.id} q={q} n={n} />)}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Stat({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/20 p-5">
      <p className="text-[11px] font-bold uppercase tracking-wider text-slate dark:text-paper/50 flex items-center gap-1.5">{icon}{label}</p>
      <p className="mt-1 font-heading font-extrabold text-xl text-ink-navy dark:text-paper">{value}</p>
    </motion.div>
  );
}

const STATUS = {
  correct: { label: "Correct", icon: Check, badge: "bg-signal-emerald text-white", card: "border-signal-emerald/30 bg-signal-emerald/5" },
  incorrect: { label: "Wrong", icon: X, badge: "bg-alert-coral text-white", card: "border-alert-coral/30 bg-alert-coral/5" },
  skipped: { label: "Not answered", icon: Minus, badge: "bg-slate/40 text-white", card: "border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/20" },
} as const;

function QuestionCard({ q, n }: { q: ScholarshipQuestionResult; n: number }) {
  const s = STATUS[q.status];
  const Icon = s.icon;
  const earned = q.marksEarned > 0 ? `+${formatMarks(q.marksEarned)}` : formatMarks(q.marksEarned);
  return (
    <div className={`rounded-2xl border p-5 space-y-3 ${s.card}`}>
      {q.caseNarrative && (
        <div className="bg-slate/5 border-l-2 border-slate/20 p-3 rounded-r-lg text-sm italic text-slate dark:text-paper/70 whitespace-pre-line">
          {q.caseNarrative}
        </div>
      )}
      <div className="flex items-start gap-3">
        <span className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5 ${s.badge}`} title={s.label}>
          <Icon className="w-3 h-3" strokeWidth={3} />
        </span>
        <p className="flex-1 text-sm font-medium text-ink-navy dark:text-paper leading-relaxed whitespace-pre-line">
          <span className="text-slate dark:text-paper/50 font-mono text-xs mr-2">Q{n}.</span>{q.text}
        </p>
        <span className="text-xs font-mono font-bold text-slate dark:text-paper/60 whitespace-nowrap">{earned}</span>
      </div>
      <div className="ml-9 space-y-1.5">
        {q.options.map((opt, i) => {
          const isRight = i === q.correctOptionIndex;
          const isMine = i === q.userSelected;
          let cls = "text-sm px-3 py-1.5 rounded-lg border ";
          if (isRight) cls += "border-signal-emerald/40 bg-signal-emerald/10 text-signal-emerald font-semibold";
          else if (isMine) cls += "border-alert-coral/40 bg-alert-coral/10 text-alert-coral";
          else cls += "border-transparent text-slate dark:text-paper/50";
          return (
            <div key={i} className={cls}>
              <span className="font-mono text-xs mr-2">{String.fromCharCode(65 + i)}.</span>
              {opt}
              {isRight && <span className="ml-2 text-xs">(correct answer)</span>}
              {isMine && <span className="ml-2 text-xs">(your answer)</span>}
            </div>
          );
        })}
      </div>
      {q.explanation && (
        <p className="ml-9 pt-2 border-t border-line-gray-light dark:border-line-gray-dark text-xs text-slate dark:text-paper/60 leading-relaxed whitespace-pre-line">
          <span className="font-semibold text-ink-navy dark:text-paper/80">Explanation: </span>{q.explanation}
        </p>
      )}
    </div>
  );
}
