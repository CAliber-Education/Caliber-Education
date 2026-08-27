"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, notFound } from "next/navigation";
import { motion } from "framer-motion";
import { useAuth } from "@/context/AuthContext";
import { ArrowLeft, Zap, Lock, Unlock, BookOpen, Clock, ArrowRight, Layers, Target, TrendingUp } from "lucide-react";

export default function SeriesDetailPage({ params }: { params: Promise<{ seriesId: string }> }) {
  const { seriesId } = use(params);
  const router = useRouter();
  const { isAuthenticated } = useAuth();

  const [series, setSeries] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [is404, setIs404] = useState(false);

  useEffect(() => {
    const fetchSeries = async () => {
      try {
        const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
        const res = await fetch(`${apiURL}/api/mcq-series/${seriesId}`);
        if (res.status === 404) { setIs404(true); return; }
        if (res.ok) {
          const data = await res.json();
          setSeries(data);
        }
      } catch (e) {
        console.warn(e);
      } finally {
        setLoading(false);
      }
    };
    fetchSeries();
  }, [seriesId]);

  if (is404) return notFound();

  if (loading || !series) {
    return (
      <div className="pt-24 pb-20 max-w-6xl mx-auto px-6 sm:px-8 space-y-10">
        <div className="h-24 bg-line-gray-light/40 dark:bg-line-gray-dark/30 rounded-2xl animate-pulse" />
        <div className="grid sm:grid-cols-2 gap-6">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-44 bg-line-gray-light/40 dark:bg-line-gray-dark/30 rounded-2xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  const setsInSeries = series.sets || [];
  const totalQuestions = setsInSeries.reduce((sum: number, s: any) => sum + (s.questionCount || 0), 0);

  function handleAttempt(set: typeof setsInSeries[0]) {
    if (set.isLocked && !isAuthenticated) {
      router.push("/login");
      return;
    }
    router.push(`/quiz/${set.id}`);
  }

  return (
    <div className="pt-16 pb-20">
      {/* Breadcrumb */}
      <div className="max-w-6xl mx-auto px-6 sm:px-8 pt-8">
        <Link href="/mcq" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper transition-colors mb-6">
          <ArrowLeft className="w-4 h-4" /> All Series
        </Link>
      </div>

      <div className="max-w-6xl mx-auto px-6 sm:px-8 space-y-12">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          className="relative overflow-hidden rounded-3xl border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/20 p-7 sm:p-10 shadow-sm"
        >
          <div className="absolute -top-24 -right-24 w-72 h-72 bg-signal-emerald/10 blur-[90px] rounded-full pointer-events-none" />

          <div className="relative space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-lg bg-line-gray-light/60 dark:bg-line-gray-dark/40 text-slate dark:text-paper/80">
                {series.subject}
              </span>
            </div>
            <h1 className="font-heading font-extrabold text-3xl sm:text-4xl text-ink-navy dark:text-paper leading-tight tracking-tight">
              {series.title}
            </h1>
            <p className="text-slate dark:text-paper/70 leading-relaxed text-sm max-w-2xl">{series.description}</p>

            {/* Stats row */}
            <div className="flex flex-wrap items-center gap-3 pt-3">
              <div className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-line-gray-light/40 dark:bg-line-gray-dark/30 text-xs text-ink-navy dark:text-paper font-semibold">
                <Layers className="w-4 h-4 text-signal-emerald" /> {setsInSeries.length} MCQ set{setsInSeries.length !== 1 ? "s" : ""}
              </div>
              <div className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-line-gray-light/40 dark:bg-line-gray-dark/30 text-xs text-ink-navy dark:text-paper font-semibold">
                <Target className="w-4 h-4 text-signal-emerald" /> {totalQuestions} question{totalQuestions !== 1 ? "s" : ""}
              </div>
              {series.is_locked && (
                <div className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 dark:text-amber-400 font-semibold">
                  <Lock className="w-4 h-4" /> ₹{series.price.toLocaleString()} one-time
                </div>
              )}
            </div>
          </div>
        </motion.div>

        {/* Sets list */}
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-heading font-bold text-lg text-ink-navy dark:text-paper">Practice Sets in this Series</h2>
            <span className="text-xs text-slate dark:text-paper/45 flex items-center gap-1.5">
              <TrendingUp className="w-3.5 h-3.5" /> {setsInSeries.length} available
            </span>
          </div>

          {setsInSeries.length === 0 ? (
            <div className="p-8 text-center border border-dashed border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/10">
              <p className="text-xs text-slate dark:text-paper/50">No sets available in this series yet.</p>
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 gap-6">
              {setsInSeries.map((set: any, i: number) => {
                const questionCount = set.questionCount || 0;

                return (
                  <motion.div
                    key={set.id}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.15 + i * 0.04, duration: 0.3 }}
                    className="group relative flex flex-col bg-white dark:bg-line-gray-dark/20 border border-line-gray-light dark:border-line-gray-dark rounded-2xl overflow-hidden hover:border-signal-emerald/40 hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200"
                  >
                    <div className="p-5 flex flex-col flex-1 gap-3.5">
                      {/* Tags */}
                      <div className="flex items-center justify-between">
                        <span className="text-[9px] font-bold uppercase tracking-wider px-2 py-1 rounded-lg bg-line-gray-light/60 dark:bg-line-gray-dark/40 text-slate dark:text-paper/70">
                          {set.subject}
                        </span>
                      </div>

                      {/* Title & desc */}
                      <div className="flex-1">
                        <h3 className="font-heading font-bold text-base text-ink-navy dark:text-paper leading-snug group-hover:text-signal-emerald transition-colors">
                          {set.title}
                        </h3>
                        <p className="mt-1.5 text-xs text-slate dark:text-paper/60 leading-relaxed line-clamp-2">
                          {set.description}
                        </p>
                      </div>

                      {/* Stats */}
                      <div className="flex items-center gap-3 text-[10px] text-slate dark:text-paper/50 pt-1">
                        <span className="flex items-center gap-1"><Target className="w-3 h-3" /> {questionCount} questions</span>
                        <span>·</span>
                        <span>{(set.sections || []).length} section{(set.sections || []).length !== 1 ? "s" : ""}</span>
                        <span>·</span>
                        <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> ~{Math.round(questionCount * 1.5)}m</span>
                      </div>

                      {/* CTA */}
                      <div className="pt-3 border-t border-line-gray-light dark:border-line-gray-dark">
                        {!set.is_locked ? (
                          <button
                            onClick={() => handleAttempt(set)}
                            className="w-full flex items-center justify-center gap-2 py-2.5 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy text-xs font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all"
                          >
                            <Unlock className="w-3.5 h-3.5" />
                            Start Set
                            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                          </button>
                        ) : isAuthenticated ? (
                          <button
                            onClick={() => handleAttempt(set)}
                            className="w-full flex items-center justify-center gap-2 py-2.5 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy text-xs font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all"
                          >
                            <Zap className="w-3.5 h-3.5" />
                            Attempt Set
                            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                          </button>
                        ) : (
                          <button
                            onClick={() => handleAttempt(set)}
                            className="w-full flex items-center justify-center gap-2 py-2.5 border border-line-gray-light dark:border-line-gray-dark text-ink-navy dark:text-paper hover:bg-line-gray-light/40 dark:hover:bg-line-gray-dark/40 text-xs font-semibold rounded-lg active:scale-[0.98] transition-all"
                          >
                            <Lock className="w-3.5 h-3.5" />
                            Sign in to unlock
                          </button>
                        )}
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
