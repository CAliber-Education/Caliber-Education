"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, BookOpen, MessageCircle, Trophy, Zap, Users, Star } from "lucide-react";
import Image from "next/image";
import { HeroMCQCard } from "@/components/HeroMCQCard";
import { useState } from "react";
import { Turnstile } from "@/components/Turnstile";
import { WhatsAppIcon, TelegramIcon, InstagramIcon } from "@/components/SocialIcons";
import { useAuth } from "@/context/AuthContext";
import { Toast, type ToastState } from "@/components/Toast";

const SOCIAL_LINKS = {
  whatsapp: "https://chat.whatsapp.com/IbzA4aKxYFwDw7zMUcZLNG",
  telegram: "https://t.me/calibermentorship",
  instagram: "https://www.instagram.com/calibermentorship/",
};

const steps = [
  { num: "01", icon: <BookOpen className="w-5 h-5" />, title: "Enroll", desc: "Choose a CA course that matches your exam level. Pay once, access forever." },
  { num: "02", icon: <Zap className="w-5 h-5" />, title: "Practice MCQs", desc: "Attempt timed MCQ sets daily. Every question mirrors the CA exam pattern." },
  { num: "03", icon: <MessageCircle className="w-5 h-5" />, title: "Get WhatsApp Access", desc: "After enrolment, join our exclusive WhatsApp group for live doubt resolution." },
];

export default function HomeClient() {
  const [zoomedImage, setZoomedImage] = useState<string | null>(null);
  const { isAuthenticated, purchasedCourseIds } = useAuth();

  return (
    <div className="pt-16">
      {/* ─── HERO ─── */}
      <section className="relative min-h-[85vh] flex items-center overflow-hidden py-32 bg-paper dark:bg-ink-navy border-b border-line-gray-light dark:border-line-gray-dark">
        <div className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03] pointer-events-none">
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)", backgroundSize: "40px 40px" }} />
        </div>

        <div className="relative max-w-6xl mx-auto px-6 sm:px-8 py-10 w-full">
          <div className="grid lg:grid-cols-2 gap-12 xl:gap-16 items-center">

            {/* LEFT COLUMN: Flattering Text & CTA */}
            <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.5, ease: "easeOut" }} className="w-full text-center lg:text-left space-y-10">
              <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-line-gray-light/60 dark:bg-line-gray-dark/60 border border-line-gray-light dark:border-line-gray-dark rounded-full text-xs font-semibold text-slate dark:text-paper/70">
                <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse" />
                Expert CA Mentorship
              </div>
              <div className="space-y-6">
                <h1 className="font-heading text-4xl sm:text-5xl lg:text-5xl xl:text-6xl font-extrabold text-ink-navy dark:text-paper leading-[1.08] tracking-tight">
                  Guided by <span className="text-transparent bg-clip-text bg-gradient-to-r from-yellow-600 to-amber-400">the Masters.</span><br />
                  Driven by your success.
                </h1>
                <p className="text-lg text-slate dark:text-paper/70 leading-relaxed max-w-xl mx-auto lg:mx-0">
                  Join the elite. Learn from India's most brilliant Chartered Accountants who combine unmatched industry expertise with an unwavering passion for mentoring. They don't just teach the syllabus—they inspire greatness and engineer your victory.
                </p>
              </div>
              <div className="flex flex-wrap gap-4 justify-center lg:justify-start">
                <Link href="/about" className="inline-flex items-center gap-2 px-6 py-3 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all text-sm">
                  Meet Your Mentors <ArrowRight className="w-4 h-4" />
                </Link>
                <Link href="/courses#one-on-one" className="inline-flex items-center gap-2 px-6 py-3 border border-line-gray-light dark:border-line-gray-dark text-ink-navy dark:text-paper hover:bg-line-gray-light/40 dark:hover:bg-line-gray-dark/40 font-semibold rounded-lg active:scale-[0.98] transition-all text-sm">
                  <Zap className="w-4 h-4" /> Book 1:1 Session
                </Link>
              </div>

              <div className="flex items-center justify-center lg:justify-start gap-8 pt-4 border-t border-line-gray-light dark:border-line-gray-dark w-full max-w-lg mx-auto lg:mx-0">
                {[
                  { val: "300+", label: "Hours of mentoring sessions" },
                  { val: "Elite", label: "CA Faculty" },
                  { val: "4.8★", label: "Average rating" },
                ].map((s, i) => (
                  <div key={i} className="space-y-1 text-center lg:text-left">
                    <div className="font-heading font-bold text-2xl text-ink-navy dark:text-paper leading-none">{s.val}</div>
                    <div className="text-xs text-slate dark:text-paper/50">{s.label}</div>
                  </div>
                ))}
              </div>
            </motion.div>

            {/* RIGHT COLUMN: Brand Graphic */}
            <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.7, ease: "easeOut", delay: 0.2 }} className="w-full">
              <div
                className="relative w-full rounded-2xl sm:rounded-3xl overflow-hidden shadow-2xl shadow-ink-navy/10 dark:shadow-none border-[4px] sm:border-[8px] border-white dark:border-line-gray-dark/30 hover:scale-[1.02] transition-transform duration-500 cursor-zoom-in"
                onClick={() => setZoomedImage("/profile.jpg")}
              >
                <Image src="/profile.jpg" alt="CAliber — mentorship programs, career counselling, handcrafted test series, MCQ portal and skill courses" width={1254} height={1254} className="w-full h-auto object-contain" quality={95} priority />
              </div>
            </motion.div>

          </div>
        </div>
      </section>

      {/* ─── HOW IT WORKS ─── */}
      <section className="py-32 bg-paper dark:bg-ink-navy/40 border-b border-line-gray-light dark:border-line-gray-dark">
        <div className="max-w-6xl mx-auto px-6 sm:px-8">
          <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} className="text-center mb-20">
            <span className="text-xs font-semibold text-slate dark:text-paper/50 uppercase tracking-widest">How It Works</span>
            <h2 className="font-heading font-bold text-3xl sm:text-4xl text-ink-navy dark:text-paper mt-3">Three steps to exam confidence</h2>
          </motion.div>
          <div className="grid md:grid-cols-3 gap-8">
            {steps.map((step, i) => (
              <motion.div key={step.num} initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.05 }} className="flex flex-col items-center text-center space-y-5 p-6 border border-transparent hover:border-line-gray-light dark:hover:border-line-gray-dark rounded-xl transition-all duration-200">
                <div className="w-12 h-12 rounded-lg border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/30 flex items-center justify-center text-ink-navy dark:text-paper">{step.icon}</div>
                <div className="space-y-2">
                  <span className="font-mono text-xs text-slate/50 dark:text-paper/30">{step.num}</span>
                  <h3 className="font-heading font-bold text-lg text-ink-navy dark:text-paper mt-1">{step.title}</h3>
                  <p className="text-xs text-slate dark:text-paper/60 leading-relaxed max-w-xs mx-auto">{step.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── FOUNDERS' TEASER ─── */}
      <section className="py-32 bg-paper dark:bg-ink-navy border-b border-line-gray-light dark:border-line-gray-dark">
        <div className="max-w-6xl mx-auto px-6 sm:px-8">
          <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} className="text-center mb-16">
            <span className="text-xs font-semibold text-slate dark:text-paper/50 uppercase tracking-widest">The Team</span>
            <h2 className="font-heading font-bold text-3xl sm:text-4xl text-ink-navy dark:text-paper mt-3">Built by CAs who cracked the exam</h2>
          </motion.div>
          <div className="text-center mt-4">
            <Link href="/about" className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink-navy dark:text-paper hover:gap-2.5 transition-all">
              Read our full story <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* ─── FREE PRACTICE CTA ─── */}
      <section className="py-32 bg-paper dark:bg-ink-navy">
        <div className="max-w-6xl mx-auto px-6 sm:px-8">
          <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} className="relative rounded-xl border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/20 overflow-hidden">
            <div className="relative px-8 py-16 text-center max-w-2xl mx-auto space-y-6">
              <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-line-gray-light dark:bg-line-gray-dark border border-line-gray-light/55 dark:border-line-gray-dark/55 rounded-full text-xs font-semibold">
                <Trophy className="w-3.5 h-3.5 text-slate dark:text-paper/60" /> No credit card required
              </div>
              <h2 className="font-heading font-bold text-3xl sm:text-4xl text-ink-navy dark:text-paper leading-tight">
                Book 1:1 Session
              </h2>
              <p className="text-slate dark:text-paper/70 leading-relaxed">
                Talk directly to a CA mentor about your prep. Real answers to your real doubts — no pressure, no strings attached.
              </p>
              <div className="flex flex-wrap gap-4 justify-center pt-2">
                <Link href="/courses#one-on-one" className="inline-flex items-center gap-2 px-6 py-3 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all text-sm">
                  Book 1:1 Session <ArrowRight className="w-4 h-4" />
                </Link>
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ─── COMMUNITY ─── */}
      <section className="relative py-28 bg-paper dark:bg-ink-navy overflow-hidden border-b border-line-gray-light dark:border-line-gray-dark">
        <div className="absolute inset-0 opacity-[0.03] dark:opacity-[0.04] pointer-events-none text-ink-navy dark:text-paper">
          <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)", backgroundSize: "36px 36px" }} />
        </div>
        <div className="relative max-w-5xl mx-auto px-6 sm:px-8">
          <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} className="flex flex-col items-center text-center gap-3 mb-14">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-full overflow-hidden flex items-center justify-center relative bg-line-gray-light/50 dark:bg-white/10">
                <Image
                  src={isAuthenticated && purchasedCourseIds?.length > 0 ? "/PREMIUM.jpg" : "/NORMAL.jpg"}
                  alt="Caliber Education Logo"
                  fill
                  sizes="36px"
                  className="object-cover"
                />
              </div>
              <span className="font-heading font-bold text-xl text-ink-navy dark:text-paper">CAliber</span>
            </div>
            <p className="text-sm text-slate dark:text-paper/60 max-w-md">Practice like the exam. Built by CAs who cracked it.</p>
            <h2 className="font-heading font-bold text-2xl sm:text-3xl text-ink-navy dark:text-paper mt-2">Not on the platform yet? Come say hi first.</h2>
          </motion.div>

          <div className="grid sm:grid-cols-3 gap-5 max-w-3xl mx-auto">
            {[
              { href: SOCIAL_LINKS.whatsapp, icon: <WhatsAppIcon className="w-7 h-7" />, label: "WhatsApp Group", desc: "Doubt-clearing with real mentors", ring: "hover:border-[#25D366]/50" },
              { href: SOCIAL_LINKS.telegram, icon: <TelegramIcon className="w-7 h-7" />, label: "Telegram Channel", desc: "Daily updates & resources", ring: "hover:border-[#26A5E4]/50" },
              { href: SOCIAL_LINKS.instagram, icon: <InstagramIcon className="w-7 h-7" />, label: "Instagram", desc: "Behind the scenes & tips", ring: "hover:border-[#C13584]/50" },
            ].map((s, i) => (
              <motion.a
                key={s.label}
                href={s.href}
                target="_blank"
                rel="noopener noreferrer"
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.06 }}
                className={`group flex flex-col items-center text-center gap-3 p-6 rounded-xl border border-line-gray-light dark:border-white/10 bg-white dark:bg-white/5 shadow-sm dark:shadow-none hover:bg-line-gray-light/40 dark:hover:bg-white/[0.08] ${s.ring} transition-all duration-200`}
              >
                <div className="w-14 h-14 rounded-full bg-white border border-line-gray-light dark:border-transparent flex items-center justify-center group-hover:scale-105 transition-transform">
                  {s.icon}
                </div>
                <div>
                  <p className="font-heading font-semibold text-sm text-ink-navy dark:text-paper">{s.label}</p>
                  <p className="text-xs text-slate dark:text-paper/50 mt-0.5">{s.desc}</p>
                </div>
              </motion.a>
            ))}
          </div>
        </div>
      </section>

      {/* ─── FOOTER ─── */}
      <Footer />

      {/* FULLSCREEN IMAGE MODAL */}
      {zoomedImage && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-ink-navy/95 backdrop-blur-sm cursor-zoom-out p-4 sm:p-8"
          onClick={() => setZoomedImage(null)}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="relative max-w-7xl max-h-[90vh] w-full h-full flex items-center justify-center"
          >
            <Image src={zoomedImage} alt="Zoomed view" fill className="object-contain drop-shadow-2xl" quality={95} />
          </motion.div>
          <button
            onClick={() => setZoomedImage(null)}
            className="absolute top-6 right-6 w-10 h-10 bg-white/10 hover:bg-white/20 rounded-full flex items-center justify-center text-white transition-colors"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}

function Footer() {
  const [formState, setFormState] = useState({ name: "", email: "", message: "" });
  const [submitted, setSubmitted] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState("");
  const [toast, setToast] = useState<ToastState | null>(null);
  const { isAuthenticated, purchasedCourseIds } = useAuth();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!turnstileToken) {
      setToast({ type: "error", message: "Please wait for security verification to complete." });
      return;
    }
    try {
      const apiURL = process.env.NEXT_PUBLIC_API_URL || "";
      const res = await fetch(`${apiURL}/api/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...formState, turnstileToken }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Submission failed");
      }
      setSubmitted(true);
    } catch (err: any) {
      setToast({ type: "error", message: err.message || "Couldn't send your message — please try again in a moment." });
    }
  }

  return (
    <footer className="bg-white dark:bg-ink-navy text-ink-navy dark:text-paper border-t border-line-gray-light dark:border-line-gray-dark">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <div className="max-w-6xl mx-auto px-6 sm:px-8 py-20">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-12">
          <div className="lg:col-span-1 space-y-4">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full overflow-hidden flex items-center justify-center relative bg-white/10">
                <Image
                  src={isAuthenticated && purchasedCourseIds?.length > 0 ? "/PREMIUM.jpg" : "/NORMAL.jpg"}
                  alt="Caliber Education Logo"
                  fill
                  sizes="32px"
                  className="object-cover"
                />
              </div>
              <span className="font-heading font-bold text-lg">CAliber</span>
            </div>
            <p className="text-xs text-slate dark:text-paper/60 leading-relaxed">Practice like the exam. Built by CAs who cracked it.</p>
            <p className="text-[10px] text-slate/40 dark:text-paper/40">Founded by a team of CAs</p>
            <div className="flex items-center gap-3 pt-1">
              <a href={SOCIAL_LINKS.whatsapp} target="_blank" rel="noopener noreferrer" aria-label="WhatsApp" className="opacity-70 hover:opacity-100 hover:scale-110 transition-all">
                <WhatsAppIcon className="w-4 h-4" />
              </a>
              <a href={SOCIAL_LINKS.telegram} target="_blank" rel="noopener noreferrer" aria-label="Telegram" className="opacity-70 hover:opacity-100 hover:scale-110 transition-all">
                <TelegramIcon className="w-4 h-4" />
              </a>
              <a href={SOCIAL_LINKS.instagram} target="_blank" rel="noopener noreferrer" aria-label="Instagram" className="opacity-70 hover:opacity-100 hover:scale-110 transition-all">
                <InstagramIcon className="w-4 h-4" />
              </a>
            </div>
          </div>

          <div>
            <h4 className="font-heading font-semibold text-xs text-ink-navy dark:text-paper mb-4 uppercase tracking-wider">Platform</h4>
            <ul className="space-y-2.5">
              {[
                { href: "/courses", label: "All Courses" },
                { href: "/courses", label: "Course Listings" },
                { href: "/dashboard", label: "Dashboard" },
              ].map((l) => (
                <li key={l.label}>
                  <Link href={l.href} className="text-xs text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper transition-colors">{l.label}</Link>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="font-heading font-semibold text-xs text-ink-navy dark:text-paper mb-4 uppercase tracking-wider">Company</h4>
            <ul className="space-y-2.5">
              {[
                { href: "/about", label: "Team" },
                { href: "/login", label: "Sign In" },
                { href: "/signup", label: "Sign Up" },
              ].map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className="text-xs text-slate dark:text-paper/60 hover:text-ink-navy dark:hover:text-paper transition-colors">{l.label}</Link>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="font-heading font-semibold text-xs text-ink-navy dark:text-paper mb-4 uppercase tracking-wider">Contact Us</h4>
            {submitted ? (
              <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="flex items-center gap-2 text-xs text-slate dark:text-paper/70 font-semibold">
                <Star className="w-4 h-4 fill-slate-500 text-slate-500" />
                Message received! We will reply within 24 hours.
              </motion.div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-3">
                <input type="text" placeholder="Your name" required value={formState.name} onChange={(e) => setFormState({ ...formState, name: e.target.value })}
                  className="w-full px-3 py-2 text-xs border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/50 text-ink-navy dark:text-paper rounded-lg focus:outline-none focus:border-ink-navy dark:focus:border-paper transition-colors" />
                <input type="email" placeholder="Email address" required value={formState.email} onChange={(e) => setFormState({ ...formState, email: e.target.value })}
                  className="w-full px-3 py-2 text-xs border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/50 text-ink-navy dark:text-paper rounded-lg focus:outline-none focus:border-ink-navy dark:focus:border-paper transition-colors" />
                <textarea placeholder="Your message" required rows={3} value={formState.message} onChange={(e) => setFormState({ ...formState, message: e.target.value })}
                  className="w-full px-3 py-2 text-xs border border-line-gray-light dark:border-line-gray-dark bg-white dark:bg-line-gray-dark/50 text-ink-navy dark:text-paper rounded-lg focus:outline-none focus:border-ink-navy dark:focus:border-paper transition-colors resize-none" />
                {/* Turnstile widget key */}
                <Turnstile onVerify={setTurnstileToken} className="mt-1" />

                <button type="submit" className="w-full py-2 bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy text-xs font-semibold rounded-lg hover:opacity-90 active:scale-[0.98] transition-all">
                  Send Message
                </button>
              </form>
            )}
          </div>
        </div>
      </div>
    </footer>
  );
}
