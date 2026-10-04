"use client";

// "Import from PDF" and "Upload JSON" for the MCQ paper editor. Both end in
// the same backend step (/api/admin/mcq-import/normalize), so either way the
// editor receives the same shape: answers never guessed, missing ones left
// unset and flagged, each case study whole and in its own section.
//
// PDF: the browser drives the parts one short request at a time
// (extract → convert per part → normalize), waiting out the AI's free-tier
// per-minute limit with a visible countdown instead of one long request.

import React, { useRef, useState } from "react";
import { FileUp, FileJson, Loader2, AlertTriangle, X } from "lucide-react";

export interface ImportedQuestion {
  type: "normal" | "case";
  case_narrative: string;
  content: string;
  options: string[];
  correct_option: number | null;
  explanation: string;
  marks: number;
  negative_marks: number;
  difficulty: string;
  review: string[];
}

export interface ImportResult {
  meta: { title: string | null; level: string | null; subject: string | null; duration_minutes: number | null; total_marks: number | null };
  sections: { title: string; questions: ImportedQuestion[] }[];
  issues: string[];
  stats: { questions: number; answered: number; flagged: number; sections: number };
}

const MAX_PDF_MB = 15;

class Cancelled extends Error {}

function api(path: string, init: RequestInit = {}) {
  const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
  const token = localStorage.getItem("caliber_jwt") || "";
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (typeof init.body === "string") headers["Content-Type"] = "application/json";
  return fetch(`${apiURL}/api/admin/mcq-import${path}`, { ...init, headers });
}

async function errorText(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  return typeof data.detail === "string" ? data.detail : fallback;
}

async function normalize(parts: unknown[]): Promise<ImportResult> {
  const res = await api("/normalize", { method: "POST", body: JSON.stringify({ parts }) });
  if (!res.ok) throw new Error(await errorText(res, "The questions couldn't be read."));
  return res.json();
}

type Progress =
  | { phase: "reading" }
  | { phase: "converting"; part: number; total: number; label: string }
  | { phase: "waiting"; part: number; total: number; seconds: number }
  | { phase: "finishing" };

export default function ImportButtons({
  onImported,
  onError,
}: {
  onImported: (result: ImportResult, source: string) => void;
  onError: (message: string) => void;
}) {
  const jsonInput = useRef<HTMLInputElement>(null);
  const [pdfOpen, setPdfOpen] = useState(false);
  const [jsonBusy, setJsonBusy] = useState(false);

  async function handleJson(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow picking the same file again
    if (!file) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch (err) {
      onError(`"${file.name}" isn't valid JSON${err instanceof Error ? ` (${err.message})` : ""}. Check the file and try again.`);
      return;
    }
    setJsonBusy(true);
    try {
      onImported(await normalize([parsed]), file.name);
    } catch (err) {
      onError(err instanceof Error ? err.message : "The file couldn't be imported.");
    } finally {
      setJsonBusy(false);
    }
  }

  return (
    <>
      <button type="button" onClick={() => setPdfOpen(true)}
        className="flex items-center gap-2 bg-ink-navy text-paper dark:bg-paper dark:text-ink-navy px-4 py-2 rounded-lg font-extrabold shadow-sm text-xs hover:opacity-90 transition-all">
        <FileUp className="w-3.5 h-3.5" /> Import from PDF
      </button>
      <input type="file" accept=".json,application/json" className="hidden" ref={jsonInput} onChange={handleJson} />
      <button type="button" disabled={jsonBusy} onClick={() => jsonInput.current?.click()}
        className="flex items-center gap-2 border border-line-gray-light dark:border-line-gray-dark text-ink-navy dark:text-paper px-4 py-2 rounded-lg font-bold text-xs hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 transition-all disabled:opacity-50">
        {jsonBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileJson className="w-3.5 h-3.5" />} Upload JSON
      </button>
      {pdfOpen && (
        <PdfImportDialog
          onClose={() => setPdfOpen(false)}
          onImported={(r, source) => { setPdfOpen(false); onImported(r, source); }}
        />
      )}
    </>
  );
}

function PdfImportDialog({ onClose, onImported }: { onClose: () => void; onImported: (r: ImportResult, source: string) => void }) {
  const [paper, setPaper] = useState<File | null>(null);
  const [answerKey, setAnswerKey] = useState<File | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cancelled = useRef(false);
  const running = progress !== null;

  function pick(setter: (f: File | null) => void) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0] || null;
      setError(null);
      if (f && f.size > MAX_PDF_MB * 1024 * 1024) {
        setError(`"${f.name}" is over ${MAX_PDF_MB} MB.`);
        setter(null);
        return;
      }
      setter(f);
    };
  }

  async function sleep(ms: number) {
    await new Promise((r) => setTimeout(r, ms));
    if (cancelled.current) throw new Cancelled();
  }

  async function start() {
    if (!paper) return;
    cancelled.current = false;
    setError(null);
    setProgress({ phase: "reading" });
    try {
      const form = new FormData();
      form.append("paper", paper);
      if (answerKey) form.append("answer_key", answerKey);
      const ex = await api("/pdf/extract", { method: "POST", body: form });
      if (!ex.ok) throw new Error(await errorText(ex, "The PDF couldn't be read."));
      const { parts } = (await ex.json()) as { parts: { label: string; text: string }[] };

      const results: unknown[] = [];
      let carry: string | null = null; // passage of a case study the previous part ended inside
      for (let i = 0; i < parts.length; i++) {
        let waits = 0;
        let glitches = 0;
        for (;;) {
          if (cancelled.current) throw new Cancelled();
          setProgress({ phase: "converting", part: i + 1, total: parts.length, label: parts[i].label });
          const res = await api("/pdf/convert", { method: "POST", body: JSON.stringify({ text: parts[i].text, carry }) });
          if (res.status === 429) {
            // Free-tier per-minute limit: wait as long as the server says, then retry this part.
            const body = await res.json().catch(() => ({}));
            let seconds = Math.ceil(Number(body.retryAfter ?? res.headers.get("retry-after") ?? 20)) || 20;
            if (++waits > 10) throw new Error("The AI stayed busy for too long. Try again in a few minutes.");
            while (seconds > 0) {
              setProgress({ phase: "waiting", part: i + 1, total: parts.length, seconds });
              await sleep(1000);
              seconds--;
            }
            continue;
          }
          if (res.status === 502 && ++glitches <= 2) continue; // an odd AI answer: retrying the part usually works
          if (!res.ok) throw new Error(await errorText(res, `Part ${i + 1} of ${parts.length} couldn't be converted.`));
          const body = await res.json();
          results.push(body.result);
          carry = body.carry ?? null;
          break;
        }
      }

      setProgress({ phase: "finishing" });
      const result = await normalize(results);
      if (cancelled.current) throw new Cancelled();
      onImported(result, answerKey ? `${paper.name} + ${answerKey.name}` : paper.name);
    } catch (err) {
      if (err instanceof Cancelled) {
        setProgress(null);
        return;
      }
      setError(err instanceof Error ? err.message : "Import failed. Please try again.");
      setProgress(null);
    }
  }

  const pct = !progress ? 0
    : progress.phase === "reading" ? 5
    : progress.phase === "finishing" ? 97
    : 5 + Math.round(((progress.part - 1) / progress.total) * 90);

  const fileBox = "flex items-center gap-3 px-3 py-2.5 rounded-xl border border-dashed border-line-gray-light dark:border-line-gray-dark cursor-pointer hover:border-signal-emerald transition-colors";

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-ink-navy/40 backdrop-blur-sm p-4" role="dialog" aria-modal="true" aria-label="Import from PDF">
      <div className="w-full max-w-lg bg-white dark:bg-ink-navy border border-line-gray-light dark:border-line-gray-dark rounded-2xl shadow-2xl p-6 space-y-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-lg font-bold text-ink-navy dark:text-paper">Import from PDF</h3>
            <p className="text-xs text-slate dark:text-paper/60 mt-1">
              Questions, options, answers and case studies are read from the paper and added for you to review.
            </p>
          </div>
          <button type="button" aria-label="Close" onClick={() => { cancelled.current = true; onClose(); }}
            className="p-1 rounded-lg text-slate hover:text-ink-navy dark:hover:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50">
            <X className="w-4 h-4" />
          </button>
        </div>

        {!running && (
          <div className="space-y-3">
            <label className={fileBox}>
              <FileUp className="w-4 h-4 text-signal-emerald shrink-0" />
              <span className="flex-1 min-w-0">
                <span className="block text-xs font-bold text-ink-navy dark:text-paper">Question paper PDF</span>
                <span className="block text-xs text-slate dark:text-paper/60 truncate">{paper ? paper.name : "Choose a file…"}</span>
              </span>
              <input type="file" accept=".pdf,application/pdf" className="hidden" onChange={pick(setPaper)} />
            </label>
            <label className={fileBox}>
              <FileUp className="w-4 h-4 text-slate shrink-0" />
              <span className="flex-1 min-w-0">
                <span className="block text-xs font-bold text-ink-navy dark:text-paper">Answer key PDF <span className="font-normal text-slate">(optional)</span></span>
                <span className="block text-xs text-slate dark:text-paper/60 truncate">{answerKey ? answerKey.name : "Only if the answers are in a separate file"}</span>
              </span>
              {answerKey && (
                <button type="button" onClick={(e) => { e.preventDefault(); setAnswerKey(null); }} className="text-xs text-slate hover:text-alert-coral">Remove</button>
              )}
              <input type="file" accept=".pdf,application/pdf" className="hidden" onChange={pick(setAnswerKey)} />
            </label>
            <p className="text-[11px] text-slate dark:text-paper/50 leading-relaxed">
              Works with typed PDFs (text you can select). Scanned or photographed papers aren&apos;t supported.
              Long papers are read in parts, and the free AI plan pauses about a minute between some of them.
            </p>
          </div>
        )}

        {running && progress && (
          <div className="space-y-3" aria-live="polite">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink-navy dark:text-paper">
              <Loader2 className="w-4 h-4 animate-spin text-signal-emerald" />
              {progress.phase === "reading" && "Reading the PDF…"}
              {progress.phase === "converting" && `Reading questions — part ${progress.part} of ${progress.total}`}
              {progress.phase === "waiting" && `Free AI limit reached — continuing in ${progress.seconds}s`}
              {progress.phase === "finishing" && "Matching answers and checking questions…"}
            </div>
            <div className="h-2 rounded-full bg-line-gray-light dark:bg-line-gray-dark overflow-hidden">
              <div className="h-full bg-signal-emerald transition-all duration-500" style={{ width: `${pct}%` }} />
            </div>
            {progress.phase === "converting" && <p className="text-xs text-slate dark:text-paper/50">{progress.label}</p>}
            {progress.phase === "waiting" && (
              <p className="text-xs text-slate dark:text-paper/50">You can leave this open — it carries on automatically.</p>
            )}
          </div>
        )}

        {error && (
          <div className="flex gap-2 rounded-xl bg-alert-coral/10 border border-alert-coral/30 px-3 py-2.5 text-xs text-alert-coral">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => { cancelled.current = true; if (!running) onClose(); }}
            className="px-4 py-2 rounded-xl text-sm font-semibold text-slate hover:text-ink-navy dark:hover:text-paper">
            {running ? "Cancel import" : "Close"}
          </button>
          {!running && (
            <button type="button" disabled={!paper} onClick={start}
              className="flex items-center gap-2 bg-signal-emerald text-white px-5 py-2 rounded-xl text-sm font-bold hover:shadow-lg transition-all disabled:opacity-40">
              <FileUp className="w-4 h-4" /> Import
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
