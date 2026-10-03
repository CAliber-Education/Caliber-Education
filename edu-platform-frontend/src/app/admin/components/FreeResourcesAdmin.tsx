"use client";

import React, { useEffect, useState } from "react";
import {
  Plus, Trash2, Edit2, ArrowUp, ArrowDown, ExternalLink, Save, X, Info,
  FolderOpen, FileText, PlayCircle, Link2,
} from "lucide-react";
import { Toast, type ToastState } from "@/components/Toast";
import {
  LEVEL_TABS, groupLabel, describeLink, isSafeUrl,
  type FreeResourceLevel, type FreeResource, type LevelCode, type LinkKind,
} from "@/lib/freeResources";

const KIND_ICON: Record<LinkKind, typeof FolderOpen> = { folder: FolderOpen, file: FileText, video: PlayCircle, link: Link2 };
const MAX_TITLE = 120;

const inp = "w-full px-3 py-2 text-sm border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/50 text-ink-navy dark:text-paper rounded-xl focus:outline-none focus:border-signal-emerald transition-colors";

function adminApi(path: string, init?: RequestInit) {
  const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
  const token = localStorage.getItem("caliber_jwt") || "";
  return fetch(`${apiURL}/api/admin/free-resources${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  });
}

async function errorText(res: Response, fallback: string): Promise<string> {
  const data = await res.json().catch(() => ({}));
  return typeof data.detail === "string" ? data.detail : fallback;
}

// Same rules the backend enforces — checked here first for instant feedback.
function validate(title: string, url: string): string | null {
  if (!title.trim()) return "Give the link a title.";
  if (title.trim().length > MAX_TITLE) return `Title must be under ${MAX_TITLE} characters.`;
  if (!isSafeUrl(url.trim())) return "Enter a full link starting with https://";
  return null;
}

export default function FreeResourcesAdmin() {
  const [levels, setLevels] = useState<FreeResourceLevel[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeLevel, setActiveLevel] = useState<LevelCode>("FINAL");
  const [toast, setToast] = useState<ToastState | null>(null);
  const [busy, setBusy] = useState(false);
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [draft, setDraft] = useState({ title: "", url: "" });
  const [editing, setEditing] = useState<{ id: string; title: string; url: string } | null>(null);
  // Bumped after every write: the list is always re-read from the server, so
  // what's shown matches what's stored (ordering is decided server-side).
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false; // ignore a response that lands after unmount/reload
    (async () => {
      try {
        const res = await adminApi("");
        if (cancelled) return;
        if (!res.ok) {
          setLoadError(await errorText(res, "Couldn't load free resources."));
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        setLevels(data.levels || []);
        setLoadError(null);
      } catch {
        if (!cancelled) setLoadError("Couldn't reach the server. Check your connection and try again.");
      }
    })();
    return () => { cancelled = true; };
  }, [reloadKey]);

  async function run(action: () => Promise<Response>, success: string, failure: string): Promise<boolean> {
    setBusy(true);
    try {
      const res = await action();
      if (!res.ok) {
        setToast({ type: "error", message: await errorText(res, failure) });
        return false;
      }
      setReloadKey((k) => k + 1);
      setToast({ type: "success", message: success });
      return true;
    } catch {
      setToast({ type: "error", message: failure });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function addLink(subjectId: string) {
    const problem = validate(draft.title, draft.url);
    if (problem) { setToast({ type: "error", message: problem }); return; }
    const ok = await run(
      () => adminApi("", { method: "POST", body: JSON.stringify({ subjectId, title: draft.title.trim(), url: draft.url.trim() }) }),
      "Link added.", "Failed to add the link.",
    );
    if (ok) { setAddingFor(null); setDraft({ title: "", url: "" }); }
  }

  async function saveEdit() {
    if (!editing) return;
    const problem = validate(editing.title, editing.url);
    if (problem) { setToast({ type: "error", message: problem }); return; }
    const ok = await run(
      () => adminApi(`/${editing.id}`, { method: "PATCH", body: JSON.stringify({ title: editing.title.trim(), url: editing.url.trim() }) }),
      "Link updated.", "Failed to update the link.",
    );
    if (ok) setEditing(null);
  }

  function move(id: string, direction: "up" | "down") {
    run(() => adminApi(`/${id}/move`, { method: "POST", body: JSON.stringify({ direction }) }), "Order updated.", "Failed to reorder.");
  }

  function remove(r: FreeResource) {
    if (!window.confirm(`Delete "${r.title}"? Students will no longer see this link.`)) return;
    run(() => adminApi(`/${r.id}`, { method: "DELETE" }), "Link deleted.", "Failed to delete the link.");
  }

  const subjects = levels?.find((l) => l.level === activeLevel)?.subjects ?? [];

  return (
    <div className="space-y-6">
      <Toast toast={toast} onDismiss={() => setToast(null)} />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-ink-navy dark:text-paper">Free Resources</h2>
          <p className="text-sm text-slate dark:text-paper/60">Links shown on the public Free Resources page, per subject.</p>
        </div>
        <a href="/free-resources" target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-2 px-4 py-2 rounded-xl border border-line-gray-light dark:border-line-gray-dark text-sm font-semibold text-ink-navy dark:text-paper hover:bg-line-gray-light/40 dark:hover:bg-line-gray-dark/40 transition-colors">
          View page <ExternalLink className="w-3.5 h-3.5" />
        </a>
      </div>

      <div className="flex gap-3 items-start rounded-xl bg-amber-400/10 border border-amber-500/30 px-4 py-3 text-xs text-ink-navy dark:text-paper/80">
        <Info className="w-4 h-4 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
        <p>
          <strong>Google Drive links:</strong> set sharing to <strong>&quot;Anyone with the link&quot; → Viewer</strong>, otherwise
          students will see &quot;Request access&quot;. Changes show on the public page within about a minute.
        </p>
      </div>

      <div className="flex gap-1 p-1 bg-line-gray-light dark:bg-line-gray-dark rounded-xl w-fit">
        {LEVEL_TABS.map((t) => (
          <button key={t.level} type="button" onClick={() => { setActiveLevel(t.level); setAddingFor(null); setEditing(null); }}
            className={`px-4 py-2 text-sm font-semibold rounded-lg transition-all ${t.level === activeLevel ? "bg-white dark:bg-ink-navy text-ink-navy dark:text-paper shadow-sm" : "text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {loadError ? (
        <div className="rounded-xl border border-alert-coral/30 bg-alert-coral/5 px-4 py-6 text-sm text-alert-coral text-center">{loadError}</div>
      ) : levels === null ? (
        <div className="text-center py-12 text-slate">Loading…</div>
      ) : subjects.length === 0 ? (
        <div className="text-center py-12 text-sm text-slate dark:text-paper/50">No subjects at this level.</div>
      ) : (
        <div className="space-y-4">
          {subjects.map((s) => {
            const meta = [s.code, groupLabel(s.groupName)].filter(Boolean).join(" · ");
            return (
              <div key={s.id} className="rounded-2xl border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/20 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-bold text-ink-navy dark:text-paper">{s.name}</h3>
                      {s.isActive === false && (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full uppercase bg-line-gray-light dark:bg-line-gray-dark text-slate dark:text-paper/60" title="This subject is hidden from students, so its links aren't shown yet.">
                          Hidden subject
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate dark:text-paper/50">
                      {meta}{meta && " · "}{s.resources.length} link{s.resources.length === 1 ? "" : "s"}
                    </p>
                  </div>
                  {addingFor !== s.id && (
                    <button type="button" disabled={busy} onClick={() => { setAddingFor(s.id); setEditing(null); setDraft({ title: "", url: "" }); }}
                      className="flex items-center gap-1.5 bg-signal-emerald text-white px-3 py-1.5 rounded-lg text-xs font-bold hover:shadow-md transition-all disabled:opacity-50">
                      <Plus className="w-3.5 h-3.5" /> Add link
                    </button>
                  )}
                </div>

                {s.resources.length > 0 && (
                  <ul className="mt-4 divide-y divide-line-gray-light dark:divide-line-gray-dark border-t border-line-gray-light dark:border-line-gray-dark">
                    {s.resources.map((r, idx) => {
                      const Icon = KIND_ICON[describeLink(r.url).kind];
                      if (editing?.id === r.id) {
                        return (
                          <li key={r.id} className="py-3 space-y-2">
                            <input className={inp} value={editing.title} maxLength={MAX_TITLE} placeholder="Title"
                              onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
                            <input className={inp} value={editing.url} placeholder="https://drive.google.com/…"
                              onChange={(e) => setEditing({ ...editing, url: e.target.value })} />
                            <div className="flex gap-2">
                              <button type="button" disabled={busy} onClick={saveEdit}
                                className="flex items-center gap-1.5 bg-signal-emerald text-white px-3 py-1.5 rounded-lg text-xs font-bold disabled:opacity-50">
                                <Save className="w-3.5 h-3.5" /> Save
                              </button>
                              <button type="button" onClick={() => setEditing(null)}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-slate hover:text-ink-navy dark:hover:text-paper">
                                <X className="w-3.5 h-3.5" /> Cancel
                              </button>
                            </div>
                          </li>
                        );
                      }
                      return (
                        <li key={r.id} className="flex items-center gap-3 py-2.5">
                          <span className="w-8 h-8 rounded-lg bg-amber-400/15 text-amber-600 dark:text-amber-400 flex items-center justify-center shrink-0">
                            <Icon className="w-4 h-4" />
                          </span>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-semibold text-ink-navy dark:text-paper truncate">{r.title}</p>
                            {isSafeUrl(r.url) ? (
                              <a href={r.url} target="_blank" rel="noopener noreferrer" className="block text-xs text-slate dark:text-paper/50 truncate hover:underline">{r.url}</a>
                            ) : (
                              <p className="text-xs text-alert-coral truncate">Invalid link — edit it</p>
                            )}
                          </div>
                          <div className="flex items-center gap-0.5 shrink-0">
                            <button type="button" aria-label="Move up" disabled={busy || idx === 0} onClick={() => move(r.id, "up")}
                              className="p-1.5 rounded-lg text-slate hover:text-ink-navy dark:hover:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 disabled:opacity-30 disabled:hover:bg-transparent">
                              <ArrowUp className="w-3.5 h-3.5" />
                            </button>
                            <button type="button" aria-label="Move down" disabled={busy || idx === s.resources.length - 1} onClick={() => move(r.id, "down")}
                              className="p-1.5 rounded-lg text-slate hover:text-ink-navy dark:hover:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 disabled:opacity-30 disabled:hover:bg-transparent">
                              <ArrowDown className="w-3.5 h-3.5" />
                            </button>
                            <button type="button" aria-label="Edit link" disabled={busy} onClick={() => { setEditing({ id: r.id, title: r.title, url: r.url }); setAddingFor(null); }}
                              className="p-1.5 rounded-lg text-slate hover:text-signal-emerald hover:bg-signal-emerald/10 disabled:opacity-30">
                              <Edit2 className="w-3.5 h-3.5" />
                            </button>
                            <button type="button" aria-label="Delete link" disabled={busy} onClick={() => remove(r)}
                              className="p-1.5 rounded-lg text-slate hover:text-alert-coral hover:bg-alert-coral/10 disabled:opacity-30">
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}

                {addingFor === s.id && (
                  <div className="mt-4 pt-4 border-t border-line-gray-light dark:border-line-gray-dark space-y-2">
                    <input className={inp} value={draft.title} maxLength={MAX_TITLE} autoFocus placeholder="Title, e.g. Chapter-wise notes"
                      onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
                    <input className={inp} value={draft.url} placeholder="Link, e.g. https://drive.google.com/drive/folders/…"
                      onChange={(e) => setDraft({ ...draft, url: e.target.value })}
                      onKeyDown={(e) => { if (e.key === "Enter") addLink(s.id); }} />
                    <div className="flex gap-2">
                      <button type="button" disabled={busy} onClick={() => addLink(s.id)}
                        className="flex items-center gap-1.5 bg-signal-emerald text-white px-3 py-1.5 rounded-lg text-xs font-bold disabled:opacity-50">
                        <Plus className="w-3.5 h-3.5" /> {busy ? "Adding…" : "Add"}
                      </button>
                      <button type="button" onClick={() => setAddingFor(null)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-slate hover:text-ink-navy dark:hover:text-paper">
                        <X className="w-3.5 h-3.5" /> Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
