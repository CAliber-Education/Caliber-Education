"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Award, Download, Eye, EyeOff, Search, Trophy, Users } from "lucide-react";
import { Toast, type ToastState } from "@/components/Toast";
import {
  formatDuration, formatMarks,
  type AdminScholarshipTest, type ScholarshipLeaderboardRow,
} from "@/lib/scholarship";

function adminApi(path: string, init?: RequestInit) {
  const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
  const token = localStorage.getItem("caliber_jwt") || "";
  return fetch(`${apiURL}/api/admin/scholarship-tests${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  });
}

async function errorText(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  return typeof data.detail === "string" ? data.detail : fallback;
}

function csvCell(v: string | number): string {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// Admin → Leaderboard: everyone who took a Scholarship Test, ranked (marks,
// then faster time), and the button that publishes results to students.
export default function ScholarshipLeaderboardAdmin() {
  const [tests, setTests] = useState<AdminScholarshipTest[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // Keyed by test id, so switching tests never shows the previous one's rows.
  const [board, setBoard] = useState<{ id: string; key: number; rows: ScholarshipLeaderboardRow[] } | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await adminApi("");
        if (cancelled) return;
        if (!res.ok) { setLoadError(await errorText(res, "Couldn't load scholarship tests.")); return; }
        const data: AdminScholarshipTest[] = await res.json();
        if (cancelled) return;
        setTests(data);
        setLoadError(null);
        setSelected((cur) => (cur && data.some((t) => t.id === cur) ? cur : data[0]?.id ?? null));
      } catch {
        if (!cancelled) setLoadError("Couldn't reach the server. Check your connection and try again.");
      }
    })();
    return () => { cancelled = true; };
  }, [reloadKey]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    (async () => {
      let next: ScholarshipLeaderboardRow[] = [];
      try {
        const res = await adminApi(`/${selected}/leaderboard`);
        if (cancelled) return;
        if (res.ok) next = (await res.json()).rows || [];
        else setToast({ type: "error", message: await errorText(res, "Couldn't load the leaderboard.") });
      } catch { /* shown as an empty board */ }
      if (!cancelled) setBoard({ id: selected, key: reloadKey, rows: next });
    })();
    return () => { cancelled = true; };
  }, [selected, reloadKey]);

  const rows = board && board.id === selected && board.key === reloadKey ? board.rows : null;

  const test = tests?.find((t) => t.id === selected) ?? null;
  const published = !!test?.resultsPublishedAt;

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!rows || !q) return rows ?? [];
    return rows.filter((r) => [r.name, r.email, r.phone].some((v) => (v || "").toLowerCase().includes(q)));
  }, [rows, query]);

  async function setPublished(value: boolean) {
    if (!test) return;
    const msg = value
      ? `Publish results for "${test.title}"? Every student who took it will see their rank, marks and answers in their dashboard.`
      : `Hide the results for "${test.title}" again? Students won't be able to open their result until you publish it.`;
    if (!window.confirm(msg)) return;
    setBusy(true);
    try {
      const res = await adminApi(`/${test.id}/publish`, { method: "POST", body: JSON.stringify({ published: value }) });
      if (!res.ok) { setToast({ type: "error", message: await errorText(res, "Couldn't update the results.") }); return; }
      setToast({ type: "success", message: value ? "Results published." : "Results hidden." });
      setReloadKey((k) => k + 1);
    } catch {
      setToast({ type: "error", message: "Couldn't reach the server. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  function downloadCsv() {
    if (!rows || !test) return;
    const header = ["Rank", "Name", "Email", "Phone", "Stage", "Marks", "Total", "Correct", "Wrong", "Not answered", "Time (s)", "Submitted"];
    const lines = rows.map((r) => [r.rank ?? "Staff test", r.name, r.email, r.phone, r.stage, r.score, r.totalMarks, r.correctCount,
      r.incorrectCount, r.skippedCount, r.timeSeconds, r.submittedAt ? new Date(r.submittedAt).toLocaleString("en-IN") : ""]);
    const csv = [header, ...lines].map((l) => l.map(csvCell).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${test.title.replace(/[^\w\- ]+/g, "").trim() || "scholarship"}-leaderboard.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (loadError) {
    return <div className="rounded-xl border border-alert-coral/30 bg-alert-coral/5 px-4 py-6 text-sm text-alert-coral text-center">{loadError}</div>;
  }
  if (tests === null) return <div className="text-center py-12 text-slate">Loading…</div>;
  if (tests.length === 0) {
    return (
      <div className="text-center py-16 border border-dashed border-line-gray-light dark:border-line-gray-dark rounded-2xl">
        <Award className="w-10 h-10 mx-auto text-amber-500 mb-3" />
        <h3 className="font-bold text-ink-navy dark:text-paper">No Scholarship Tests yet</h3>
        <p className="text-sm text-slate dark:text-paper/60 mt-1 max-w-md mx-auto">
          Create one in MCQ Hierarchy: make a paper, tick <strong>Scholarship Test</strong>, set the price and publish it.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      {tests.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {tests.map((t) => (
            <button key={t.id} type="button" onClick={() => setSelected(t.id)}
              className={`px-4 py-2 rounded-xl text-sm font-semibold border transition-colors ${t.id === selected
                ? "bg-amber-400/15 border-amber-500/60 text-ink-navy dark:text-paper"
                : "border-line-gray-light dark:border-line-gray-dark text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper"}`}>
              {t.title}
            </button>
          ))}
        </div>
      )}

      {test && (
        <div className="rounded-2xl border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/20 p-5 flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <h3 className="font-heading font-bold text-lg text-ink-navy dark:text-paper">{test.title}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate dark:text-paper/60">
              <span className="flex items-center gap-1"><Users className="w-3.5 h-3.5" /> {test.attemptCount} student{test.attemptCount === 1 ? "" : "s"} took it
                {test.staffAttemptCount > 0 && ` · ${test.staffAttemptCount} staff test${test.staffAttemptCount === 1 ? "" : "s"}`}</span>
              <span>₹{test.price} · {test.questionCount} questions · {test.durationMinutes} min</span>
              <span className={`font-bold uppercase text-[10px] px-2 py-0.5 rounded-full ${test.status === "published" ? "bg-signal-emerald/10 text-signal-emerald" : "bg-line-gray-light dark:bg-line-gray-dark text-slate dark:text-paper/60"}`}>
                {test.status === "published" ? "Open for students" : test.status}
              </span>
              <span className={`font-bold uppercase text-[10px] px-2 py-0.5 rounded-full ${published ? "bg-amber-400/20 text-amber-700 dark:text-amber-300" : "bg-line-gray-light dark:bg-line-gray-dark text-slate dark:text-paper/60"}`}>
                {published ? `Results published ${new Date(test.resultsPublishedAt!).toLocaleDateString("en-IN")}` : "Results not published"}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={downloadCsv} disabled={!rows || rows.length === 0}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-line-gray-light dark:border-line-gray-dark text-sm font-semibold text-ink-navy dark:text-paper hover:bg-line-gray-light/40 dark:hover:bg-line-gray-dark/40 disabled:opacity-50">
              <Download className="w-4 h-4" /> Download CSV
            </button>
            {published ? (
              <button type="button" disabled={busy} onClick={() => setPublished(false)}
                className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-alert-coral/40 text-sm font-semibold text-alert-coral hover:bg-alert-coral/5 disabled:opacity-50">
                <EyeOff className="w-4 h-4" /> Hide results
              </button>
            ) : (
              <button type="button" disabled={busy || !rows} onClick={() => setPublished(true)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 text-sm font-bold disabled:opacity-50">
                <Eye className="w-4 h-4" /> Publish results
              </button>
            )}
          </div>
        </div>
      )}

      {rows === null ? (
        <div className="text-center py-12 text-slate">Loading leaderboard…</div>
      ) : rows.length === 0 ? (
        <div className="text-center py-12 text-sm text-slate dark:text-paper/60 border border-dashed border-line-gray-light dark:border-line-gray-dark rounded-2xl">
          No one has taken this test yet.
        </div>
      ) : (
        <div className="space-y-3">
          <div className="relative max-w-sm">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name, email or phone"
              className="w-full pl-9 pr-3 py-2 text-sm border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/50 text-ink-navy dark:text-paper rounded-xl focus:outline-none focus:border-signal-emerald" />
          </div>
          <div className="overflow-x-auto rounded-2xl border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/20">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-slate dark:text-paper/50 border-b border-line-gray-light dark:border-line-gray-dark">
                  <th className="px-4 py-3">Rank</th>
                  <th className="px-4 py-3">Student</th>
                  <th className="px-4 py-3">Phone</th>
                  <th className="px-4 py-3 text-right">Marks</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">✓ / ✗ / –</th>
                  <th className="px-4 py-3 text-right">Time</th>
                  <th className="px-4 py-3">Submitted</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.userId} className={`border-b last:border-0 border-line-gray-light dark:border-line-gray-dark ${r.isStaff ? "opacity-70" : ""}`}>
                    <td className="px-4 py-3 font-heading font-black text-ink-navy dark:text-paper">
                      {r.rank === null ? (
                        <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full bg-line-gray-light dark:bg-line-gray-dark text-slate dark:text-paper/60 whitespace-nowrap"
                          title="Staff attempts aren't ranked, so they never push a student down.">
                          Staff test
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1">
                          {r.rank <= 3 && <Trophy className={`w-3.5 h-3.5 ${r.rank === 1 ? "text-amber-500" : r.rank === 2 ? "text-slate-400" : "text-orange-500"}`} />}
                          {r.rank}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 min-w-[180px]">
                      <div className="font-semibold text-ink-navy dark:text-paper">{r.name || "—"}</div>
                      <div className="text-xs text-slate dark:text-paper/50">{r.email}</div>
                    </td>
                    <td className="px-4 py-3 text-slate dark:text-paper/70 whitespace-nowrap">{r.phone || "—"}</td>
                    <td className="px-4 py-3 text-right font-mono font-bold text-ink-navy dark:text-paper whitespace-nowrap">
                      {formatMarks(r.score)} <span className="text-slate dark:text-paper/40 font-normal">/ {formatMarks(r.totalMarks)}</span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-slate dark:text-paper/70 whitespace-nowrap">
                      <span className="text-signal-emerald">{r.correctCount}</span> / <span className="text-alert-coral">{r.incorrectCount}</span> / {r.skippedCount}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs text-slate dark:text-paper/70 whitespace-nowrap">{formatDuration(r.timeSeconds)}</td>
                    <td className="px-4 py-3 text-xs text-slate dark:text-paper/60 whitespace-nowrap">
                      {r.submittedAt ? new Date(r.submittedAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate dark:text-paper/50">
            Ranked by marks; equal marks go to whoever finished faster. Staff test attempts are listed at the bottom but never ranked.
          </p>
        </div>
      )}
    </div>
  );
}
