"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Icon, IconName } from "@/components/Icon";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ToastProvider } from "@/components/Toast";

const NAV: { href: string; label: string; icon: IconName }[] = [
  { href: "/chat", label: "Chat", icon: "chat" },
  { href: "/knowledge", label: "Knowledge", icon: "book" },
  { href: "/memory", label: "Memory", icon: "brain" },
  { href: "/learning", label: "Learning", icon: "db" },
  { href: "/evaluation", label: "Evaluation", icon: "gauge" },
  { href: "/health", label: "Health", icon: "pulse" },
];

export default function StudioLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api<{ user: { email: string } }>("/v1/auth/me").then((r) => { if (r.ok) setEmail(r.data.user.email); else if (r.status === 401) router.replace("/login"); });
  }, [router]);
  useEffect(() => { setOpen(false); }, [path]);
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [open]);

  async function logout() { await api("/v1/auth/logout", { method: "POST", body: {} }); router.replace("/login"); }

  const nav = (
    <nav aria-label="Primary" className="flex flex-col gap-0.5">
      {NAV.map((n) => (
        <Link key={n.href} href={n.href} className="nav-link" aria-current={path === n.href ? "page" : undefined}><Icon name={n.icon} />{n.label}</Link>
      ))}
    </nav>
  );

  return (
    <ToastProvider>
      <div className="flex h-[100dvh] flex-col md:flex-row">
        {/* Mobile top bar */}
        <header className="flex items-center justify-between border-b px-3 py-2 md:hidden" style={{ borderColor: "var(--line)" }}>
          <button className="icon-btn" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)}><Icon name="menu" /></button>
          <span className="font-semibold tracking-tight">AVOENIX</span>
          <ThemeToggle />
        </header>

        {/* Sidebar (desktop) / drawer (mobile) */}
        {open && <div className="fixed inset-0 z-30 md:hidden" style={{ background: "color-mix(in srgb, var(--bg) 70%, transparent)" }} onClick={() => setOpen(false)} aria-hidden="true" />}
        <aside className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col gap-4 border-r p-3 transition-transform md:static md:w-56 md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}
               style={{ borderColor: "var(--line)", background: "var(--surface)" }} aria-label="Sidebar">
          <div className="flex items-center justify-between px-1.5 pt-1">
            <div><div className="font-semibold tracking-tight">AVOENIX</div><div className="muted text-xs">Studio · v0.0.1</div></div>
            <span className="hidden md:block"><ThemeToggle /></span>
            <button className="icon-btn md:hidden" aria-label="Close navigation" onClick={() => setOpen(false)}><Icon name="x" /></button>
          </div>
          {nav}
          <div className="mt-auto border-t px-1.5 pt-3 text-xs" style={{ borderColor: "var(--line)" }}>
            <div className="muted truncate" title={email ?? undefined}>{email ?? "…"}</div>
            <button onClick={logout} className="nav-link -ml-2 mt-1 w-full"><Icon name="logout" size={16} />Sign out</button>
          </div>
        </aside>

        <main className="min-h-0 min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </ToastProvider>
  );
}
