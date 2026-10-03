"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useAuth } from "@/context/AuthContext";
import { useTestGuard } from "@/context/TestGuardContext";
import { isStaffPanelRole, staffRoleLabel } from "@/lib/roles";
import { useEffect, useState } from "react";
import { Sun, Moon, Menu, X, LogOut, LayoutDashboard, Shield, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

const navLinks = [
  { href: "/", label: "Home" },
  { href: "/about", label: "Team" },
  { href: "/courses", label: "Courses" },
  { href: "/test-series", label: "Test Series" },
  { href: "/free-resources", label: "Free Resources" },
];

export function Navbar() {
  const { theme, setTheme } = useTheme();
  const { isAuthenticated, user, logout, purchasedCourseIds } = useAuth();
  const { isTestActive, guardNavigate, guardAction } = useTestGuard();
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  // No-op passthrough on every page except an active quiz attempt — only
  // then does clicking a nav link intercept navigation with the Leave Test
  // confirmation instead of navigating immediately.
  const guardedClick = (href: string) => (e: React.MouseEvent) => {
    if (!isTestActive) return;
    e.preventDefault();
    guardNavigate(href);
  };

  const guardedLogout = () => guardAction(logout);

  useEffect(() => {
    setMounted(true);
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <header className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${scrolled ? "bg-paper/95 dark:bg-ink-navy/95 backdrop-blur-md shadow-sm border-b border-line-gray-light dark:border-line-gray-dark" : "bg-transparent"
      }`}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">

          {/* Logo */}
          <Link href="/" onClick={guardedClick("/")} className="flex items-center gap-3 group">
            <div className="w-8 h-8 sm:w-10 sm:h-10 rounded-full overflow-hidden flex items-center justify-center group-hover:scale-105 transition-transform flex-shrink-0 relative bg-white/10">
              <Image
                src={isAuthenticated && purchasedCourseIds?.length > 0 ? "/PREMIUM.jpg" : "/NORMAL.jpg"}
                alt="Caliber Education Logo"
                fill
                sizes="40px"
                className="object-cover"
              />
            </div>
            <span className="font-heading font-bold text-lg text-ink-navy dark:text-paper tracking-tight">CAliber</span>
          </Link>

          {/* Desktop Nav */}
          <nav className="hidden md:flex items-center gap-1">
            {navLinks.map((link) => (
              <Link key={link.href} href={link.href} onClick={guardedClick(link.href)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${isActive(link.href)
                  ? "text-ink-navy dark:text-paper bg-line-gray-light/50 dark:bg-line-gray-dark/50 font-semibold"
                  : "text-slate dark:text-paper/70 hover:text-ink-navy dark:hover:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50"
                  }`}>
                {link.label}
              </Link>
            ))}
            {/* MCQ — primary pill */}
            <Link href="/mcq" onClick={guardedClick("/mcq")}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5 ${isActive("/mcq")
                ? "text-ink-navy dark:text-paper bg-line-gray-light/50 dark:bg-line-gray-dark/50 font-semibold"
                : "text-slate dark:text-paper/70 hover:text-ink-navy dark:hover:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50"
                }`}>
              <Zap className="w-3.5 h-3.5" />
              MCQ
            </Link>

            {isAuthenticated && (
              <Link href="/dashboard" onClick={guardedClick("/dashboard")}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${isActive("/dashboard")
                  ? "text-ink-navy dark:text-paper bg-line-gray-light/50 dark:bg-line-gray-dark/50 font-semibold"
                  : "text-slate dark:text-paper/70 hover:text-ink-navy dark:hover:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50"
                  }`}>
                Dashboard
              </Link>
            )}
          </nav>

          {/* Desktop Actions */}
          <div className="hidden md:flex items-center gap-2">
            {mounted && (
              <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                className="p-2 rounded-lg text-slate dark:text-paper/70 hover:bg-line-gray-light dark:hover:bg-line-gray-dark transition-colors" aria-label="Toggle theme">
                {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
            )}

            {isAuthenticated ? (
              <div className="flex items-center gap-2">
                {user && isStaffPanelRole(user.role) && (
                  <Link href="/admin" onClick={guardedClick("/admin")} className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold text-alert-coral border border-alert-coral/30 rounded-lg hover:bg-alert-coral/10 transition-colors">
                    <Shield className="w-3.5 h-3.5" /> {staffRoleLabel(user.role)}
                  </Link>
                )}
                <Link href="/profile" onClick={guardedClick("/profile")} title="My Profile"
                  className="w-9 h-9 rounded-full bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy font-heading font-bold text-sm flex items-center justify-center hover:opacity-90 active:scale-[0.96] transition-all shrink-0">
                  {user?.email?.[0]?.toUpperCase() || "?"}
                </Link>
                <button onClick={guardedLogout} className="p-2 rounded-lg text-slate dark:text-paper/70 hover:bg-line-gray-light dark:hover:bg-line-gray-dark transition-colors" aria-label="Logout">
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Link href="/login" className="px-4 py-2 text-sm font-semibold text-slate dark:text-paper/70 hover:text-ink-navy dark:hover:text-paper transition-colors">
                  Sign In
                </Link>
                <Link href="/signup" className="px-4 py-2 text-sm font-semibold bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy rounded-lg hover:opacity-90 active:scale-[0.98] transition-all">
                  Sign Up
                </Link>
              </div>
            )}
          </div>

          {/* Mobile: theme + hamburger */}
          <div className="flex md:hidden items-center gap-2">
            {mounted && (
              <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} className="p-2 rounded-lg text-slate dark:text-paper/70" aria-label="Toggle theme">
                {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
            )}
            <button onClick={() => setMenuOpen(!menuOpen)} className="p-2 rounded-lg text-slate dark:text-paper/70" aria-label="Toggle menu">
              {menuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu */}
      <AnimatePresence>
        {menuOpen && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
            className="md:hidden bg-paper dark:bg-ink-navy border-b border-line-gray-light dark:border-line-gray-dark overflow-hidden">
            <div className="px-4 py-4 space-y-1">
              {navLinks.map((link) => (
                <Link key={link.href} href={link.href} onClick={(e) => { guardedClick(link.href)(e); if (!e.defaultPrevented) setMenuOpen(false); }}
                  className={`block px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${isActive(link.href) ? "text-ink-navy dark:text-paper bg-line-gray-light/50 dark:bg-line-gray-dark/50 font-semibold" : "text-slate dark:text-paper/70 hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50"
                    }`}>
                  {link.label}
                </Link>
              ))}
              <Link href="/mcq" onClick={(e) => { guardedClick("/mcq")(e); if (!e.defaultPrevented) setMenuOpen(false); }}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${isActive("/mcq") ? "text-ink-navy dark:text-paper bg-line-gray-light/50 dark:bg-line-gray-dark/50 font-semibold" : "text-slate dark:text-paper/70 hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50"
                  }`}>
                <Zap className="w-3.5 h-3.5" /> MCQ
              </Link>

              <div className="pt-2 border-t border-line-gray-light dark:border-line-gray-dark">
                {isAuthenticated ? (
                  <div className="space-y-1">
                    <Link href="/dashboard" onClick={(e) => { guardedClick("/dashboard")(e); if (!e.defaultPrevented) setMenuOpen(false); }} className="block px-4 py-2.5 text-sm font-semibold text-ink-navy dark:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 rounded-lg">Dashboard</Link>
                    <Link href="/profile" onClick={(e) => { guardedClick("/profile")(e); if (!e.defaultPrevented) setMenuOpen(false); }} className="flex items-center gap-2 px-4 py-2.5 text-sm font-semibold text-ink-navy dark:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 rounded-lg">
                      <span className="w-5 h-5 rounded-full bg-ink-navy dark:bg-paper text-paper dark:text-ink-navy font-heading font-bold text-[10px] flex items-center justify-center shrink-0">
                        {user?.email?.[0]?.toUpperCase() || "?"}
                      </span>
                      My Profile
                    </Link>
                    {user && isStaffPanelRole(user.role) && (
                      <Link href="/admin" onClick={(e) => { guardedClick("/admin")(e); if (!e.defaultPrevented) setMenuOpen(false); }} className="flex items-center gap-2 px-4 py-2.5 text-sm font-semibold text-alert-coral hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 rounded-lg">
                        <Shield className="w-3.5 h-3.5" /> {staffRoleLabel(user.role)}
                      </Link>
                    )}
                    <button onClick={() => { guardedLogout(); setMenuOpen(false); }} className="block w-full text-left px-4 py-2.5 text-sm font-medium text-slate dark:text-paper/70 hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 rounded-lg">Sign Out</button>
                  </div>
                ) : (
                  <div className="space-y-1">
                    <Link href="/login" onClick={() => setMenuOpen(false)} className="block px-4 py-2.5 text-sm font-medium text-slate dark:text-paper/70 hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 rounded-lg">Sign In</Link>
                    <Link href="/signup" onClick={() => setMenuOpen(false)} className="block px-4 py-2.5 text-sm font-bold text-ink-navy dark:text-paper hover:bg-line-gray-light/50 dark:hover:bg-line-gray-dark/50 rounded-lg">Sign Up</Link>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
