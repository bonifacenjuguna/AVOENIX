"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

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
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-4 px-4">
      <h1 className="text-2xl font-semibold">AVOENIX Studio</h1>
      <p className="muted text-sm">Admin sign-in. Platform v0.0.0 — an algorithmic intelligence system, not a language model.</p>
      <form onSubmit={submit} className="card flex flex-col gap-3 p-4">
        <label className="text-sm">Email<input className="input mt-1" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="text-sm">Password<input className="input mt-1" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <button className="btn" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}
