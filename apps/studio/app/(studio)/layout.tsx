"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const NAV = [
  { href: "/chat", label: "Chat", ms: "1" },
  { href: "/health", label: "Health & diagnostics", ms: "1" },
  { href: "/memory", label: "Memory", ms: "2" },
  { href: "/knowledge", label: "Knowledge", ms: "2" },
  { href: "/learning", label: "Learning", ms: "3" },
  { href: "/evaluation", label: "Evaluation", ms: "4" },
];

export default function StudioLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    api<{ user: { email: string } }>("/v1/auth/me").then((r) => { if (r.ok) setEmail(r.data.user.email); else if (r.status === 401) router.replace("/login"); });
  }, [router]);

  async function logout() { await api("/v1/auth/logout", { method: "POST", body: {} }); router.replace("/login"); }

  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col gap-1 border-b p-3 md:w-56 md:border-b-0 md:border-r" style={{ borderColor: "var(--line)" }}>
        <div className="px-2 pb-2 text-lg font-semibold">AVOENIX <span className="badge muted">v0.0.0</span></div>
        <nav className="flex flex-wrap gap-1 md:flex-col">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={`rounded-md px-2 py-1.5 text-sm ${path === n.href ? "font-semibold" : "muted"}`} style={path === n.href ? { background: "var(--card)" } : undefined}>
              {n.label}{n.ms !== "1" && <span className="badge muted ml-2">M{n.ms}</span>}
            </Link>
          ))}
        </nav>
        <div className="mt-auto hidden px-2 pt-4 text-xs md:block">
          <div className="muted truncate">{email ?? "…"}</div>
          <button onClick={logout} className="mt-1 underline">Sign out</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-4">{children}</main>
    </div>
  );
}
