"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    const r = await api("/v1/auth/login", { method: "POST", body: { email, password } });
    setBusy(false);
    if (r.ok) router.replace("/chat");
    else setError(r.error.code === "rate_limited" ? "Too many attempts. Wait a moment and try again." : r.error.message);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-5 px-4">
      <div className="absolute right-3 top-3"><ThemeToggle /></div>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">AVOENIX</h1>
        <p className="muted mt-1 text-sm">Algorithmic Intelligence, Engineered to Evolve.</p>
      </div>
      <form onSubmit={submit} className="card flex flex-col gap-3 p-5" aria-describedby={error ? "login-error" : undefined}>
        <label className="text-sm font-medium">Email<input className="input mt-1 font-normal" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="text-sm font-medium">Password<input className="input mt-1 font-normal" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p id="login-error" role="alert" className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>}
        <button className="btn" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="muted text-xs">Admin sign-in · platform v0.0.1 · an algorithmic system, not a language model.</p>
    </main>
  );
}
