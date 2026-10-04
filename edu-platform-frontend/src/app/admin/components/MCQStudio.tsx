"use client";

import React, { useState, useEffect } from "react";
import { Plus, Edit2, Trash2, ArrowLeft, Save, AlertCircle, FileText, Settings2, GripVertical, CheckCircle, ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Toast, type ToastState } from "@/components/Toast";
import { useAuth } from "@/context/AuthContext";
import ImportButtons, { type ImportResult } from "./McqImport";

// -- Models matching Backend V3 Schema --
export interface Question {
  id: string;
  type: "normal" | "case";
  content: string;
  options: string[];
  // null only for an imported question whose answer wasn't in the file —
  // Save is blocked until one is picked.
  correct_option: number | null;
  explanation: string;
  marks: number;
  negative_marks: number;
  difficulty: "easy" | "medium" | "hard";
  case_narrative?: string;
  case_group_id?: string;
  case_scenario_id?: string;
  review?: string[]; // import notes to check; editor-only, ignored on save
}

function hasValidAnswer(q: { correct_option: number | null; options: string[] }): boolean {
  return Number.isInteger(q.correct_option) && (q.correct_option as number) >= 0 && (q.correct_option as number) < q.options.length;
}

// Unique-match a subject named in an imported paper ("FINANCIAL REPORTING")
// to the live catalog, at the detected level when known. Ambiguous → none.
function matchSubject(subject: string | null, level: string | null, live: LiveSubject[]): LiveSubject | null {
  if (!subject) return null;
  const norm = (s: string) => s.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, " ").trim();
  const want = norm(subject);
  const pool = level ? live.filter((s) => s.level === level) : live;
  const hits = pool.filter((s) => {
    const name = norm(s.name);
    return name === want || norm(s.code) === want || (name.length > 3 && want.includes(name));
  });
  return hits.length === 1 ? hits[0] : null;
}

export interface CaseScenario {
  id: string;
  narrative: string;
}

export interface ExamSection {
  id: string;
  title: string;
  questions: Question[];
}

export interface MCQPaper {
  id: string;
  title: string;
  level: string;
  groupName: string;
  subjectCode: string;
  chapterName?: string;
  testType: string;
  durationMinutes: number;
  passingMarks: number;
  totalMarks: number;
  status: "draft" | "published" | "archived";
  shuffleQuestions: boolean;
  shuffleOptions: boolean;
  sections: ExamSection[];
  case_scenarios?: CaseScenario[]; // we manage cases per paper here
  sectionCount?: number;
  questionCount?: number;
  createdByEmail?: string | null; // set when an MCQ editor created it
}

// Master Data
// Master Data — aligned with ca_level/ca_group DB enums
const LEVELS = ["FINAL", "INTERMEDIATE", "FOUNDATION"];
const GROUPS = ["GROUP_1", "GROUP_2", "BOTH", "NONE"];
const TEST_TYPES = ["COMPLETE_GROUP", "FULL_SUBJECT", "CHAPTER_WISE"];
const LEVEL_LABELS: Record<string, string> = { FINAL: "CA Final", INTERMEDIATE: "CA Intermediate", FOUNDATION: "CA Foundation" };
const GROUP_LABELS: Record<string, string> = { GROUP_1: "Group I", GROUP_2: "Group II", BOTH: "Both Groups", NONE: "All Subjects" };

// Subjects are fetched live from /api/mcq/packages (the real mcq_subjects
// catalog) — NOT hardcoded here. A hardcoded list previously used different
// codes than the actual storefront (e.g. "Adv Acc" vs the real "ADV_ACC"),
// which silently broke the purchase-access check: a paper saved with a code
// that didn't match any real subject could never be unlocked by a buyer.
interface LiveSubject { code: string; name: string; level: string; group_name: string; }

export default function MCQStudio({ series }: { series: any[] }) {
  // An MCQ editor sees only their own papers (the backend filters the list),
  // and manages them without an admin — including publishing.
  const { user } = useAuth();
  const isMcqEditor = user?.role === "mcq_editor";
  const [papers, setPapers] = useState<MCQPaper[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingPaper, setEditingPaper] = useState<MCQPaper | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  useEffect(() => {
    fetchPapers();
  }, []);

  async function fetchPapers() {
    setLoading(true);
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";
      const res = await fetch(`${apiURL}/api/admin/mcq-sets`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setPapers(data.map((p: any) => ({
          ...p,
          groupName: p.groupName || p.group_name || "",
          subjectCode: p.subjectCode || p.subject_code || "",
          testType: p.testType || p.test_type || "FULL_SUBJECT",
          durationMinutes: p.durationMinutes || p.duration_minutes || 0,
          passingMarks: p.passingMarks || p.passing_marks || 0,
          totalMarks: p.totalMarks || p.total_marks || 0,
          shuffleQuestions: p.shuffleQuestions || p.shuffle_questions || false,
          shuffleOptions: p.shuffleOptions || p.shuffle_options || false,
          sectionCount: p.sectionCount || p.section_count || 0,
          questionCount: p.questionCount || p.question_count || 0
        })));
      }
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  }

  async function handleDelete(paperId: string, paperTitle: string) {
    if (!window.confirm(`Delete "${paperTitle}" permanently? This cannot be undone.`)) return;
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";
      const res = await fetch(`${apiURL}/api/admin/mcq-sets/${paperId}`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        setPapers(prev => prev.filter(p => p.id !== paperId));
      } else {
        setToast({ type: "error", message: "Delete failed. Try again." });
      }
    } catch {
      setToast({ type: "error", message: "Error deleting paper." });
    }
  }

  function handleCreate() {
    setEditingPaper({
      id: "",
      title: "New Test Paper",
      level: "FINAL",
      groupName: "GROUP_1",
      subjectCode: "FR",
      testType: "FULL_SUBJECT",
      durationMinutes: 60,
      passingMarks: 40,
      totalMarks: 100,
      status: "draft",
      shuffleQuestions: false,
      shuffleOptions: false,
      sections: [],
      case_scenarios: []
    });
  }

  if (editingPaper) {
    return <PaperEditor paper={editingPaper} onBack={() => { setEditingPaper(null); fetchPapers(); }} />;
  }

  return (
    <div className="space-y-6">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-ink-navy dark:text-paper">MCQ Papers (CA Hierarchy)</h2>
          <p className="text-sm text-slate dark:text-paper/60">
            {isMcqEditor
              ? "Create and publish MCQ papers in the hierarchy. You only see the papers you've created."
              : "Manage mock tests, question banks, and case scenarios."}
          </p>
        </div>
        <button onClick={handleCreate} className="flex items-center gap-2 bg-signal-emerald text-white px-4 py-2 rounded-xl font-bold hover:shadow-lg transition-all">
          <Plus className="w-4 h-4" /> New Paper
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-slate">Loading papers...</div>
      ) : papers.length === 0 ? (
        <div className="text-center py-16 border-2 border-dashed border-line-gray-light dark:border-line-gray-dark rounded-2xl bg-white dark:bg-line-gray-dark/10 space-y-4">
          <p className="text-lg font-bold text-ink-navy dark:text-paper">No MCQ Papers Yet</p>
          <p className="text-sm text-slate dark:text-paper/50">Create your first paper to get started.</p>
          <button onClick={handleCreate} className="inline-flex items-center gap-2 bg-signal-emerald text-white px-5 py-2.5 rounded-xl font-bold hover:bg-signal-emerald/90 transition-all">
            <Plus className="w-4 h-4" /> Create First Paper
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {papers.map(p => (
            <div key={p.id} className="bg-white dark:bg-line-gray-dark/50 p-6 rounded-2xl border border-line-gray-light dark:border-line-gray-dark shadow-sm hover:shadow-md transition-shadow">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <span className={`text-[10px] font-bold px-2 py-1 rounded-full uppercase ${p.status === 'published' ? 'bg-signal-emerald/10 text-signal-emerald' : 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'}`}>
                    {p.status}
                  </span>
                  <h3 className="font-bold text-ink-navy dark:text-paper mt-2">{p.title}</h3>
                  {!isMcqEditor && p.createdByEmail && (
                    <p className="text-[11px] text-purple-600 dark:text-purple-400 font-semibold mt-1">Created by {p.createdByEmail}</p>
                  )}
                </div>
                <div className="flex gap-1">
                  <button onClick={() => setEditingPaper(p)} className="p-2 text-slate hover:text-signal-emerald hover:bg-signal-emerald/10 rounded-lg transition-colors">
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button onClick={() => handleDelete(p.id, p.title)} className="p-2 text-slate hover:text-alert-coral hover:bg-alert-coral/10 rounded-lg transition-colors">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="space-y-2 mb-6">
                <div className="flex items-center text-sm text-slate dark:text-paper/70">
                  <span className="w-20 font-medium">Hierarchy:</span>
                  <span className="text-xs bg-slate/10 px-2 py-0.5 rounded text-ink-navy dark:text-paper">{p.level} • {p.groupName}</span>
                </div>
                <div className="flex items-center text-sm text-slate dark:text-paper/70">
                  <span className="w-20 font-medium">Subject:</span>
                  <span className="font-semibold text-signal-emerald">{p.subjectCode}</span>
                </div>
                <div className="flex items-center text-sm text-slate dark:text-paper/70">
                  <span className="w-20 font-medium">Type:</span>
                  <span className="text-xs border border-line-gray-light dark:border-line-gray-dark px-2 py-0.5 rounded">{(p.testType || "FULL_SUBJECT").replace("_", " ")}</span>
                </div>
              </div>

              <div className="flex items-center justify-between border-t border-line-gray-light dark:border-line-gray-dark pt-4">
                <div className="text-center">
                  <p className="text-2xl font-black text-ink-navy dark:text-paper">{p.durationMinutes}</p>
                  <p className="text-[10px] uppercase text-slate font-bold">Mins</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-black text-ink-navy dark:text-paper">{p.totalMarks}</p>
                  <p className="text-[10px] uppercase text-slate font-bold">Marks</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-black text-ink-navy dark:text-paper">{p.questionCount || 0}</p>
                  <p className="text-[10px] uppercase text-slate font-bold">Qs</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PaperEditor({ paper, onBack }: { paper: MCQPaper, onBack: () => void }) {
  const [data, setData] = useState<MCQPaper>(paper);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<"settings" | "cases" | "questions">("settings");
  const [liveSubjects, setLiveSubjects] = useState<LiveSubject[]>([]);
  const [toast, setToast] = useState<ToastState | null>(null);

  const inp = "w-full px-3 py-2 text-sm border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/50 text-ink-navy dark:text-paper rounded-xl focus:outline-none focus:border-signal-emerald transition-colors";

  useEffect(() => {
    const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
    fetch(`${apiURL}/api/mcq/packages`)
      .then((r) => (r.ok ? r.json() : { allSubjects: [] }))
      .then((d) => setLiveSubjects((d.allSubjects || []).map((s: any) => ({
        code: s.code, name: s.name, level: s.level, group_name: s.group_name,
      }))))
      .catch(() => setLiveSubjects([]));
  }, []);

  useEffect(() => {
    if (!paper.id) return; // new paper — no fetch needed
    const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
    const token = localStorage.getItem("caliber_jwt") || "";
    fetch(`${apiURL}/api/admin/mcq-sets/${paper.id}`, {
      headers: { "Authorization": `Bearer ${token}` }
    })
      .then(res => {
        if (!res.ok) throw new Error(`${res.status}`);
        return res.json();
      })
      .then(full => setData(prev => ({ ...prev, sections: full.sections || [], case_scenarios: full.case_scenarios || [] })))
      .catch(() => {/* keep existing data on auth error */});
  }, [paper.id]);

  async function handleSave() {
    if (!data.title.trim()) { setToast({ type: "error", message: "Give this paper a title before saving." }); return; }
    if (!data.subjectCode) { setToast({ type: "error", message: "Select a subject before saving — the paper can't be saved without one." }); return; }

    let questionNumber = 0;
    for (const sec of data.sections || []) {
      for (const q of sec.questions || []) {
        questionNumber++;
        if (!q.content || !q.content.trim()) {
          setToast({ type: "error", message: `Question ${questionNumber} (in section "${sec.title}") is missing its question text. Fill it in before saving.` });
          return;
        }
        if (!q.options || q.options.length === 0 || q.options.some((opt: string) => !opt || !opt.trim())) {
          setToast({ type: "error", message: `Question ${questionNumber} (in section "${sec.title}") has a blank answer option. Fill in every option before saving.` });
          return;
        }
        if (!hasValidAnswer(q)) {
          setToast({ type: "error", message: `Question ${questionNumber} (in section "${sec.title}") has no correct answer selected. Pick the right option before saving.` });
          return;
        }
      }
    }

    setSaving(true);
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const token = localStorage.getItem("caliber_jwt") || "";
      const res = await fetch(`${apiURL}/api/admin/mcq-sets`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify(data)
      });
      if (res.ok) {
        setToast({ type: "success", message: "Saved successfully!" });
        setTimeout(onBack, 900);
      } else {
        const err = await res.json().catch(() => ({}));
        setToast({ type: "error", message: err.detail || "Failed to save. Please check every field and try again." });
      }
    } catch (e) {
      setToast({ type: "error", message: "Error saving paper. Please check your connection and try again." });
    }
    setSaving(false);
  }

  // BOTH/NONE = cross-group test, show all subjects at that level
  const filteredSubjects = liveSubjects.filter(s =>
    s.level === data.level &&
    (data.groupName === "BOTH" || data.groupName === "NONE" || s.group_name === data.groupName)
  );

  return (
    <div className="space-y-6">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <div className="flex items-center justify-between pb-4 border-b border-line-gray-light dark:border-line-gray-dark">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="p-2 bg-line-gray-light dark:bg-line-gray-dark rounded-full hover:bg-slate/20 transition-colors">
            <ArrowLeft className="w-5 h-5 text-ink-navy dark:text-paper" />
          </button>
          <h2 className="text-xl font-bold text-ink-navy dark:text-paper">
            {paper.id ? "Edit Paper" : "Create New Paper"}
          </h2>
        </div>
        <button onClick={handleSave} disabled={saving} className="flex items-center gap-2 bg-signal-emerald text-white px-6 py-2 rounded-xl font-bold hover:shadow-lg transition-all disabled:opacity-50">
          <Save className="w-4 h-4" /> {saving ? "Saving..." : "Save Paper"}
        </button>
      </div>

      <div className="flex gap-2 border-b border-line-gray-light dark:border-line-gray-dark">
        {[
          { id: "settings", icon: <Settings2 className="w-4 h-4" />, label: "Hierarchy & Settings" },
          { id: "questions", icon: <CheckCircle className="w-4 h-4" />, label: "Sections & Questions" },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id as any)}
            className={`flex items-center gap-2 px-4 py-3 font-semibold text-sm transition-colors border-b-2 ${activeTab === t.id ? "border-signal-emerald text-signal-emerald" : "border-transparent text-slate hover:text-ink-navy dark:hover:text-paper"}`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {activeTab === "settings" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="space-y-4">
            <h3 className="font-bold text-lg text-ink-navy dark:text-paper border-b border-line-gray-light dark:border-line-gray-dark pb-2">Basic Info</h3>
            <div>
              <label className="block text-xs font-bold text-slate uppercase mb-1">Title</label>
              <input className={inp} value={data.title} onChange={e => setData({ ...data, title: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold text-slate uppercase mb-1">Status</label>
                <select className={inp} value={data.status} onChange={e => setData({ ...data, status: e.target.value as any })}>
                  <option value="draft">Draft</option>
                  <option value="published">Published</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-bold text-slate uppercase mb-1">Test Type</label>
                <select className={inp} value={data.testType} onChange={e => setData({ ...data, testType: e.target.value })}>
                  {TEST_TYPES.map(t => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
                </select>
              </div>
            </div>
            {data.status === "draft" && (
              <p className="text-[11px] font-semibold text-amber-600 bg-amber-500/10 rounded-lg px-3 py-2">
                This paper is in Draft — it will NOT appear in the student catalog, &quot;My MCQs&quot;, or be attemptable until you set Status to Published.
              </p>
            )}

            <h3 className="font-bold text-lg text-ink-navy dark:text-paper border-b border-line-gray-light dark:border-line-gray-dark pb-2 mt-8">CA Hierarchy Mapping</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold text-slate uppercase mb-1">Level</label>
                <select className={inp} value={data.level} onChange={e => {
                  const newLevel = e.target.value;
                  // Only clear the subject if it's actually invalid for the
                  // new level — re-selecting the same level (or a level that
                  // happens to share the subject) must never silently wipe
                  // an already-correct selection.
                  const stillValid = liveSubjects.some(s => s.code === data.subjectCode && s.level === newLevel);
                  setData({ ...data, level: newLevel, subjectCode: stillValid ? data.subjectCode : "" });
                }}>
                  {LEVELS.map(t => <option key={t} value={t}>{LEVEL_LABELS[t] ?? t}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-bold text-slate uppercase mb-1">Group</label>
                <select className={inp} value={data.groupName} onChange={e => {
                  const newGroup = e.target.value;
                  const stillValid = liveSubjects.some(s => s.code === data.subjectCode && s.level === data.level &&
                    (newGroup === "BOTH" || newGroup === "NONE" || s.group_name === newGroup));
                  setData({ ...data, groupName: newGroup, subjectCode: stillValid ? data.subjectCode : "" });
                }}>
                  {GROUPS.map(t => <option key={t} value={t}>{GROUP_LABELS[t] ?? t}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="block text-xs font-bold text-slate uppercase mb-1">Subject</label>
              <select className={inp} value={data.subjectCode} onChange={e => setData({ ...data, subjectCode: e.target.value })}>
                <option value="">-- Select Subject --</option>
                {filteredSubjects.length === 0
                  ? <option disabled>No subjects for {data.level} / {data.groupName}</option>
                  : filteredSubjects.map(s => <option key={s.code} value={s.code}>{s.code} — {s.name}</option>)
                }
              </select>
            </div>
            {data.testType === "CHAPTER_WISE" && (
              <div>
                <label className="block text-xs font-bold text-slate uppercase mb-1">Chapter Name</label>
                <input className={inp} placeholder="e.g. Chapter 4: Capital Gains" value={data.chapterName || ""} onChange={e => setData({ ...data, chapterName: e.target.value })} />
              </div>
            )}
          </div>

          <div className="space-y-4">
            <h3 className="font-bold text-lg text-ink-navy dark:text-paper border-b border-line-gray-light dark:border-line-gray-dark pb-2">Grading & Rules</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-bold text-slate uppercase mb-1">Duration (Mins)</label>
                <input type="number" className={inp} value={data.durationMinutes} onChange={e => setData({ ...data, durationMinutes: parseInt(e.target.value) || 0 })} />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate uppercase mb-1">Total Marks</label>
                <input type="number" className={inp} value={data.totalMarks} onChange={e => setData({ ...data, totalMarks: parseInt(e.target.value) || 0 })} />
              </div>
              <div>
                <label className="block text-xs font-bold text-slate uppercase mb-1">Passing Marks</label>
                <input type="number" className={inp} value={data.passingMarks} onChange={e => setData({ ...data, passingMarks: parseInt(e.target.value) || 0 })} />
              </div>
            </div>
            <div className="p-4 bg-line-gray-light dark:bg-line-gray-dark/50 rounded-xl space-y-3 mt-4">
              <label className="flex items-center gap-3 cursor-pointer text-sm font-semibold text-ink-navy dark:text-paper">
                <input type="checkbox" checked={data.shuffleQuestions} onChange={e => setData({ ...data, shuffleQuestions: e.target.checked })} className="w-4 h-4 text-signal-emerald rounded border-slate" />
                Shuffle Questions
              </label>
              <label className="flex items-center gap-3 cursor-pointer text-sm font-semibold text-ink-navy dark:text-paper">
                <input type="checkbox" checked={data.shuffleOptions} onChange={e => setData({ ...data, shuffleOptions: e.target.checked })} className="w-4 h-4 text-signal-emerald rounded border-slate" />
                Shuffle Options
              </label>
            </div>
          </div>
        </div>
      )}

      {activeTab === "questions" && (
        <QuestionsStudio data={data} setData={setData} inp={inp} setToast={setToast} liveSubjects={liveSubjects} />
      )}
    </div>
  );
}

interface ImportSummary { source: string; questions: number; applied: string[]; issues: string[] }

const ANSWER_NOTE_MARKER = "pick the correct option";

// What still needs a person's eye on a question: a missing answer (live —
// clears the moment one is picked) plus any import notes not yet checked.
function attentionFor(q: Question): { answerNote: string | null; notes: string[] } {
  const review = q.review || [];
  const answerNote = hasValidAnswer(q)
    ? null
    : review.find((m) => m.includes(ANSWER_NOTE_MARKER)) || "No correct answer selected — pick the right option.";
  return { answerNote, notes: review.filter((m) => !m.includes(ANSWER_NOTE_MARKER)) };
}

function QuestionsStudio({ data, setData, inp, setToast, liveSubjects }: any) {
  const [summary, setSummary] = useState<ImportSummary | null>(null);

  // Imports (PDF or JSON) arrive already checked by the backend: answers that
  // weren't in the file are null and flagged, never defaulted to option A.
  function applyImport(result: ImportResult, source: string) {
    const existing = (data.sections || []).reduce((n: number, s: ExamSection) => n + (s.questions?.length || 0), 0);
    if (existing > 0 && !window.confirm(
      `This paper already has ${existing} question${existing === 1 ? "" : "s"}. ` +
      `The ${result.stats.questions} imported question${result.stats.questions === 1 ? "" : "s"} will be added after them.\n\nContinue?`
    )) return;

    const stamp = Date.now();
    const newSections = result.sections.map((sec, sIdx) => ({
      id: `sec-imp-${stamp}-${sIdx}`,
      title: sec.title,
      questions: sec.questions.map((q, qIdx) => ({
        id: `q-imp-${stamp}-${sIdx}-${qIdx}`,
        type: q.type,
        content: q.content,
        options: q.options.length ? q.options : ["", ""],
        correct_option: q.correct_option,
        explanation: q.explanation,
        marks: q.marks,
        negative_marks: q.negative_marks,
        difficulty: q.difficulty,
        case_narrative: q.case_narrative,
        review: q.review,
      })),
    }));

    // Paper details from the file only fill a fresh paper, so importing into
    // a paper you've already set up never overwrites its settings.
    const updates: Partial<MCQPaper> = {};
    const applied: string[] = [];
    const issues = [...result.issues];
    if (existing === 0) {
      const m = result.meta;
      if (m.title && (!data.title?.trim() || data.title === "New Test Paper")) { updates.title = m.title; applied.push("title"); }
      if (m.duration_minutes) { updates.durationMinutes = m.duration_minutes; applied.push(`duration (${m.duration_minutes} min)`); }
      if (m.total_marks) {
        updates.totalMarks = m.total_marks;
        applied.push(`total marks (${m.total_marks})`);
        // Untouched defaults are 40 of 100; keep that 40% rather than leave a
        // passing mark above the paper's total.
        if (data.passingMarks === 40 && data.totalMarks === 100) {
          updates.passingMarks = Math.round(m.total_marks * 0.4 * 2) / 2;
          applied.push(`passing marks (40% = ${updates.passingMarks})`);
        }
      }
      const subject = matchSubject(m.subject, m.level, liveSubjects || []);
      if (subject) {
        Object.assign(updates, { level: subject.level, groupName: subject.group_name, subjectCode: subject.code });
        applied.push(`subject (${subject.code} — ${subject.name})`);
      } else if (m.subject) {
        issues.push(`Subject "${m.subject}" wasn't recognised — set it on Hierarchy & Settings.`);
      }
    }
    setData({ ...data, ...updates, sections: [...(data.sections || []), ...newSections] });
    setSummary({ source, questions: result.stats.questions, applied, issues });
    setToast({ type: "success", message: `Imported ${result.stats.questions} question${result.stats.questions === 1 ? "" : "s"}.` });
  }

  const needingAttention = (data.sections || []).reduce((n: number, s: ExamSection) =>
    n + (s.questions || []).filter((q: Question) => { const a = attentionFor(q); return a.answerNote || a.notes.length; }).length, 0);

  function addOption(secIdx: number, qIdx: number) {
    const newSecs = [...data.sections];
    newSecs[secIdx].questions[qIdx].options = [...newSecs[secIdx].questions[qIdx].options, ""];
    setData({ ...data, sections: newSecs });
  }

  function addEmptySection() {
    setData({
      ...data,
      sections: [...(data.sections || []), { id: `sec-${Date.now()}`, title: "New Section", questions: [] }]
    });
  }

  function addQuestion(secIdx: number, type: 'normal' | 'case') {
    const newSecs = [...data.sections];
    if (!newSecs[secIdx].questions) newSecs[secIdx].questions = [];
    newSecs[secIdx].questions.push({
      id: `q-${Date.now()}`,
      type,
      content: "",
      options: ["", "", "", ""],
      correct_option: 0,
      marks: type === 'case' ? 2 : 1,
      negative_marks: 0,
      difficulty: "medium",
      ...(type === 'case' ? { case_narrative: "" } : {})
    });
    setData({ ...data, sections: newSecs });
  }

  function updateQuestion(secIdx: number, qIdx: number, field: string, value: any) {
    const newSecs = [...data.sections];
    newSecs[secIdx].questions[qIdx][field] = value;
    setData({ ...data, sections: newSecs });
  }

  function addSubQuestion(secIdx: number, parentQIdx: number) {
    const newSecs = [...data.sections];
    if (!newSecs[secIdx].questions) newSecs[secIdx].questions = [];
    newSecs[secIdx].questions.splice(parentQIdx + 1, 0, {
      id: `q-${Date.now()}`,
      type: 'case',
      content: "",
      options: ["", "", "", ""],
      correct_option: 0,
      marks: 2,
      negative_marks: 0,
      difficulty: "medium",
      // Sub-questions don't carry their own editable narrative (only the case
      // block's first/head question shows that textarea — see isCaseHead
      // below), but every question in the run is denormalized with the full
      // narrative text server-side on save, so this key must always exist.
      case_narrative: ""
    });
    setData({ ...data, sections: newSecs });
  }

  function updateOption(secIdx: number, qIdx: number, optIdx: number, value: string) {
    const newSecs = [...data.sections];
    newSecs[secIdx].questions[qIdx].options[optIdx] = value;
    setData({ ...data, sections: newSecs });
  }

  function deleteQuestion(secIdx: number, qIdx: number) {
    const newSecs = [...data.sections];
    newSecs[secIdx].questions.splice(qIdx, 1);
    setData({ ...data, sections: newSecs });
  }

  return (
    <div className="space-y-4 shadow-sm">
      <div className="flex justify-between items-center pb-2 border-b border-line-gray-light dark:border-line-gray-dark">
        <p className="text-sm text-slate dark:text-paper/70 font-semibold">Manage Sections & Inject Questions</p>
        <div className="flex items-center gap-3">
          <button onClick={addEmptySection} className="flex items-center gap-2 bg-line-gray-light dark:bg-line-gray-dark px-4 py-2 rounded-lg font-bold text-xs hover:opacity-80">
            <Plus className="w-3.5 h-3.5" /> Manual Section
          </button>
          <ImportButtons onImported={applyImport} onError={(message) => setToast({ type: "error", message })} />
        </div>
      </div>

      {summary && (
        <div className="relative rounded-xl border border-signal-emerald/30 bg-signal-emerald/5 px-4 py-3 pr-20 text-xs space-y-1.5 text-ink-navy dark:text-paper/80">
          <button type="button" onClick={() => setSummary(null)} className="absolute top-2.5 right-3 text-xs font-semibold text-slate hover:text-ink-navy dark:hover:text-paper">Dismiss</button>
          <p className="font-bold text-ink-navy dark:text-paper">Imported {summary.questions} question{summary.questions === 1 ? "" : "s"} from {summary.source}.</p>
          {needingAttention > 0 ? (
            <p className="font-semibold text-amber-700 dark:text-amber-400">
              {needingAttention} question{needingAttention === 1 ? " needs" : "s need"} your attention — highlighted in yellow below. Save stays blocked until each has an answer.
            </p>
          ) : (
            <p className="font-semibold text-signal-emerald">Nothing flagged — still give the answers a quick check before saving.</p>
          )}
          {summary.applied.length > 0 && <p>Also filled in on Hierarchy &amp; Settings: {summary.applied.join(", ")}.</p>}
          {summary.issues.map((issue) => <p key={issue} className="text-amber-700 dark:text-amber-400">⚠ {issue}</p>)}
        </div>
      )}

      <div className="space-y-4 pt-2">
        {(!data.sections || data.sections.length === 0) ? (
          <div className="text-center py-16 border-2 border-dashed border-line-gray-light dark:border-line-gray-dark rounded-2xl bg-white dark:bg-line-gray-dark/20">
            <p className="text-slate dark:text-paper font-black text-lg mb-2">Paper is Currently Empty!</p>
            <p className="text-sm text-slate/70 dark:text-paper/60 max-w-md mx-auto">Add a section by hand, or use Import from PDF or Upload JSON to fill in the whole paper at once.</p>
          </div>
        ) : (
          data.sections.map((sec: any, idx: number) => (
            <div key={sec.id} className="p-5 border border-line-gray-light dark:border-line-gray-dark rounded-xl bg-white dark:bg-line-gray-dark/30 shadow-md">
              <div className="flex items-center justify-between mb-4">
                <input className="font-heading font-black text-lg bg-transparent focus:outline-none border-b border-transparent focus:border-signal-emerald text-ink-navy dark:text-paper transition w-2/3" value={sec.title} onChange={(e) => {
                  const newSecs = [...data.sections];
                  newSecs[idx].title = e.target.value;
                  setData({ ...data, sections: newSecs });
                }} />
                <div className="flex gap-2">
                  <button onClick={() => addQuestion(idx, 'normal')} className="px-3 py-1.5 bg-slate/10 hover:bg-slate/20 text-xs font-bold rounded-lg transition-colors">
                    + Normal Q
                  </button>
                  <button onClick={() => addQuestion(idx, 'case')} className="px-3 py-1.5 bg-yellow-100 dark:bg-yellow-900/30 hover:bg-yellow-200 dark:hover:bg-yellow-900/50 text-yellow-700 dark:text-yellow-400 text-xs font-bold rounded-lg transition-colors">
                    + Case Block
                  </button>
                </div>
              </div>

              {sec.questions && sec.questions.length > 0 && (
                <div className="space-y-6">
                  {sec.questions.map((q: any, qIdx: number) => {
                    // A case block's narrative is edited on exactly one
                    // question: the first one in its contiguous run. Every
                    // other question in the same run is a sub-question that
                    // shares the same narrative (denormalized server-side on
                    // save) but has no narrative editor of its own — gated by
                    // array position, not by which questions happen to carry
                    // a case_narrative value, so this stays correct both for
                    // brand-new blocks and for blocks reloaded from the DB
                    // (where every row in the run now carries the narrative).
                    const isCaseHead = q.type === 'case' && (qIdx === 0 || sec.questions[qIdx - 1]?.type !== 'case');
                    const { answerNote, notes } = attentionFor(q);
                    const needsAttention = !!answerNote || notes.length > 0;
                    return (
                    <div key={q.id} className={`p-4 bg-white dark:bg-line-gray-dark/50 border rounded-xl space-y-4 relative group ${needsAttention ? "border-amber-400 dark:border-amber-500/70 ring-1 ring-amber-400/40" : "border-line-gray-light dark:border-line-gray-dark"}`}>

                      <button onClick={() => deleteQuestion(idx, qIdx)} className="absolute top-3 right-3 text-red-500 opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-red-50 dark:hover:bg-red-500/20 rounded">
                        <Trash2 className="w-4 h-4" />
                      </button>

                      {needsAttention && (
                        <div className="rounded-lg bg-amber-400/10 border border-amber-400/40 px-3 py-2 text-xs text-amber-800 dark:text-amber-300 space-y-1 mr-8">
                          {answerNote && <p>• {answerNote}</p>}
                          {notes.map((n) => <p key={n}>• {n}</p>)}
                          {notes.length > 0 && (
                            <button type="button" onClick={() => updateQuestion(idx, qIdx, 'review', [])} className="font-bold underline underline-offset-2 hover:opacity-80">
                              Mark as checked
                            </button>
                          )}
                        </div>
                      )}

                      <div className="flex items-center gap-2 mb-2">
                        <span className={`px-2 py-0.5 text-[10px] font-black uppercase tracking-widest rounded ${q.type === 'case' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' : 'bg-slate/20 text-slate'}`}>{q.type === 'case' ? (isCaseHead ? 'CASE NARRATIVE + Q1' : 'CASE SUB-QUESTION') : 'NORMAL Q'}</span>
                        <span className="text-xs font-bold text-slate">Marks: <input type="number" step="0.5" className="w-12 bg-transparent border-b outline-none text-center" value={q.marks} onChange={e => updateQuestion(idx, qIdx, 'marks', Number(e.target.value))} /></span>
                        <span className="text-xs font-bold text-slate">Neg: <input type="number" step="0.01" className="w-12 bg-transparent border-b outline-none text-center" value={q.negative_marks} onChange={e => updateQuestion(idx, qIdx, 'negative_marks', Number(e.target.value))} /></span>
                      </div>

                      {isCaseHead && (
                        <div className="mb-4">
                          <label className="text-[10px] uppercase font-bold text-yellow-600 dark:text-yellow-400 mb-1 block">Case Narrative Passage</label>
                          <textarea className={inp} rows={3} placeholder="Provide the long case study reading passage here..." value={q.case_narrative || ""} onChange={e => updateQuestion(idx, qIdx, 'case_narrative', e.target.value)} />

                          <button onClick={() => addSubQuestion(idx, qIdx)} className="mt-2 text-[10px] uppercase font-black text-white bg-ink-navy dark:bg-paper dark:text-ink-navy px-3 py-1.5 rounded hover:opacity-80 transition-opacity">
                            + Add Linked Sub-Question Below
                          </button>
                        </div>
                      )}

                      <div>
                        <label className="text-[10px] uppercase font-bold text-slate mb-1 block">Question / Sub-Question</label>
                        <textarea className={inp} rows={2} placeholder="Type the question..." value={q.content} onChange={e => updateQuestion(idx, qIdx, 'content', e.target.value)} />
                      </div>

                      <div className="grid grid-cols-2 gap-3">
                        {q.options.map((opt: string, optIdx: number) => (
                          <div key={optIdx} className="flex items-center gap-2">
                            <input type="radio" name={`correct-${idx}-${qIdx}`} checked={q.correct_option === optIdx} onChange={() => updateQuestion(idx, qIdx, 'correct_option', optIdx)} className="w-4 h-4 text-signal-emerald" />
                            <input className={inp} placeholder={`Option ${optIdx + 1}`} value={opt} onChange={e => updateOption(idx, qIdx, optIdx, e.target.value)} />
                          </div>
                        ))}
                      </div>
                      {q.options.length < 4 && (
                        <button type="button" onClick={() => addOption(idx, qIdx)} className="text-xs font-bold text-signal-emerald hover:underline">
                          + Add option
                        </button>
                      )}

                      <div>
                        <label className="text-[10px] uppercase font-bold text-slate mb-1 block">Explanation (Optional)</label>
                        <input className={inp} placeholder="Why is this correct?" value={q.explanation || ""} onChange={e => updateQuestion(idx, qIdx, 'explanation', e.target.value)} />
                      </div>
                    </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
