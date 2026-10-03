"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, ExternalLink, FolderOpen, FileText, PlayCircle, Link2 } from "lucide-react";
import {
  LEVEL_TABS, groupLabel, describeLink, isSafeUrl,
  type FreeResourceLevel, type LevelCode, type LinkKind,
} from "@/lib/freeResources";

export type { FreeResourceLevel };

const KIND_ICON: Record<LinkKind, typeof FolderOpen> = {
  folder: FolderOpen,
  file: FileText,
  video: PlayCircle,
  link: Link2,
};

export default function FreeResourcesClient({ levels }: { levels: FreeResourceLevel[] | null }) {
  const [activeLevel, setActiveLevel] = useState<LevelCode>("FINAL");
  // Several subjects can be open at once, so students can compare.
  const [open, setOpen] = useState<Set<string>>(new Set());

  const subjects = levels?.find((l) => l.level === activeLevel)?.subjects ?? [];

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="pt-16 min-h-screen bg-paper dark:bg-ink-navy">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12 sm:py-16">
        <motion.header initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mb-10">
          <h1 className="relative inline-block font-heading font-extrabold text-3xl sm:text-4xl text-ink-navy dark:text-paper">
            Free Resources
            <span aria-hidden className="absolute left-0 -bottom-1.5 h-1 w-full rounded-full bg-gradient-to-r from-yellow-600 to-amber-400" />
          </h1>
          <p className="mt-5 text-sm sm:text-base text-slate dark:text-paper/60 max-w-xl">
            Free notes, question banks and past papers for every CA subject.
          </p>
        </motion.header>

        <div role="tablist" aria-label="CA level" className="flex flex-wrap justify-center gap-1.5 sm:gap-3 mb-8">
          {LEVEL_TABS.map((t) => {
            const active = t.level === activeLevel;
            return (
              <button
                key={t.level}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setActiveLevel(t.level)}
                className={`px-4 sm:px-5 py-2 rounded-full border font-heading font-bold text-sm sm:text-base transition-colors ${active
                  ? "bg-amber-400/15 border-amber-500/70 text-ink-navy dark:bg-amber-400/10 dark:border-amber-400/60 dark:text-paper"
                  : "border-transparent text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper"
                  }`}
              >
                {t.label}
              </button>
            );
          })}
        </div>

        {levels === null ? (
          <p className="text-center py-16 text-sm text-slate dark:text-paper/60">
            We couldn&apos;t load the resources right now. Please refresh the page in a moment.
          </p>
        ) : subjects.length === 0 ? (
          <p className="text-center py-16 text-sm text-slate dark:text-paper/60">No subjects for this level yet.</p>
        ) : (
          <ul className="space-y-3">
            {subjects.map((s, i) => {
              const isOpen = open.has(s.id);
              const links = s.resources.filter((r) => isSafeUrl(r.url));
              // Codes like QUANT_APT are internal ids, so students see only the group.
              const meta = groupLabel(s.groupName);
              return (
                <motion.li
                  key={`${activeLevel}-${s.id}`}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className={`rounded-xl border bg-white dark:bg-line-gray-dark/20 overflow-hidden transition-colors ${isOpen
                    ? "border-amber-500/50 dark:border-amber-400/40"
                    : "border-line-gray-light dark:border-line-gray-dark hover:border-slate/40 dark:hover:border-paper/30"
                    }`}
                >
                  <button
                    type="button"
                    onClick={() => toggle(s.id)}
                    aria-expanded={isOpen}
                    aria-controls={`free-res-${s.id}`}
                    className="w-full flex items-center gap-4 px-5 sm:px-6 py-4 text-left"
                  >
                    <span className="flex-1 min-w-0">
                      <span className="block font-heading font-bold text-base sm:text-lg text-ink-navy dark:text-paper">{s.name}</span>
                      {meta && <span className="block text-xs text-slate dark:text-paper/50 mt-0.5">{meta}</span>}
                    </span>
                    <span className="hidden sm:block text-xs text-slate dark:text-paper/50 whitespace-nowrap">
                      {links.length === 0 ? "Coming soon" : `${links.length} resource${links.length === 1 ? "" : "s"}`}
                    </span>
                    <ChevronRight className={`w-5 h-5 shrink-0 text-ink-navy dark:text-paper transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`} />
                  </button>

                  <AnimatePresence initial={false}>
                    {isOpen && (
                      <motion.div
                        id={`free-res-${s.id}`}
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <div className="border-t border-line-gray-light dark:border-line-gray-dark px-3 sm:px-4 py-2">
                          {links.length === 0 ? (
                            <p className="px-2 py-4 text-sm text-slate dark:text-paper/60">
                              No resources for this subject yet — check back soon.
                            </p>
                          ) : (
                            <ul className="divide-y divide-line-gray-light dark:divide-line-gray-dark">
                              {links.map((r) => {
                                const info = describeLink(r.url);
                                const Icon = KIND_ICON[info.kind];
                                return (
                                  <li key={r.id}>
                                    <a
                                      href={r.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="group flex items-center gap-3 px-2 py-3 rounded-lg hover:bg-line-gray-light/40 dark:hover:bg-line-gray-dark/40 transition-colors"
                                    >
                                      <span className="w-9 h-9 rounded-lg bg-amber-400/15 text-amber-600 dark:text-amber-400 flex items-center justify-center shrink-0">
                                        <Icon className="w-4 h-4" />
                                      </span>
                                      <span className="flex-1 min-w-0">
                                        <span className="block text-sm font-semibold text-ink-navy dark:text-paper truncate">{r.title}</span>
                                        <span className="block text-xs text-slate dark:text-paper/50 truncate">{info.label}</span>
                                      </span>
                                      <span className="flex items-center gap-1 text-xs font-semibold text-ink-navy dark:text-paper opacity-60 group-hover:opacity-100 transition-opacity">
                                        Open <ExternalLink className="w-3.5 h-3.5" />
                                      </span>
                                    </a>
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
