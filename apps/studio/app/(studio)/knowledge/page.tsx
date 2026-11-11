"use client";
import { useState } from "react";
import { Status, useGet } from "@/components/Panel";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";

const VERIFICATION = ["", "verified", "curated", "supported", "unverified", "contradicted", "conflicting"];

export default function Knowledge() {
  const toast = useToast();
  const [tab, setTab] = useState<"claims" | "conflicts" | "facts">("claims");
  return (
    <div className="mx-auto max-w-5xl space-y-3 p-4 sm:p-6">
      <h1 className="text-xl font-semibold tracking-tight">Knowledge</h1>
      <Status level="partial">Remembering what you said is not the same as believing it. Each user statement is a claim with provenance and a verification state; only curated seed knowledge is treated as established, and it is not independently verified.</Status>
      <div role="tablist" aria-label="Knowledge views" className="flex gap-1">
        {(["claims", "conflicts", "facts"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`btn ${tab === t ? "" : "btn-ghost"}`} onClick={() => setTab(t)}>{t === "facts" ? "Facts (raw)" : t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>
      {tab === "claims" && <Claims />}
      {tab === "conflicts" && <Conflicts onToast={toast} />}
      {tab === "facts" && <Facts />}
    </div>
  );
}

function Claims() {
  const [v, setV] = useState("");
  const { loading, data, error } = useGet(`/v1/claims${v ? `?verification=${v}` : ""}`);
  const [open, setOpen] = useState<string | null>(null);
  const hist = useGet(open ? `/v1/claims/${open}/history` : null);
  return (
    <section className="space-y-2">
      <label className="text-sm">Verification state <select className="input ml-2 w-auto" value={v} onChange={(e) => setV(e.target.value)}>{VERIFICATION.map((x) => <option key={x} value={x}>{x || "all"}</option>)}</select></label>
      {loading && <div className="skeleton h-16" aria-busy="true" />}
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      {data && (
        <ul className="card divide-y text-sm" style={{ borderColor: "var(--line)" }}>
          {data.claims.length === 0 && <li className="muted p-3">No claims recorded. State a fact in Chat (for example “The capital of Atlantis is Poseidonis.”) to create one.</li>}
          {data.claims.map((c: any) => (
            <li key={c.id} className="p-3" style={{ borderColor: "var(--line)" }}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="badge">{c.verification}</span><span className="badge">{c.provenance}</span>
                <span className="font-medium">{c.statement ?? `${c.subject?.label ?? ""} ${c.predicate} ${c.object?.label ?? ""}`}</span>
                <button className="btn btn-ghost ml-auto" style={{ minHeight: 28 }} onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>History</button>
              </div>
              <p className="muted mt-1 text-xs">{c.assessment?.level ?? "—"} · interpretation {c.assessment?.interpretation_confidence ?? "—"} · factual support {c.assessment?.support ?? "none"}{c.memory_id ? " · linked to the conversation memory" : ""}</p>
              {open === c.id && (
                <div className="mt-2 rounded-lg p-2 text-xs" style={{ background: "var(--surface-2)" }}>
                  {hist.loading ? "Loading…" : hist.error ? hist.error : <pre className="max-h-64 overflow-auto">{JSON.stringify(hist.data, null, 1)}</pre>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Conflicts({ onToast }: { onToast: (m: string, k?: "ok" | "error") => void }) {
  const [status, setStatus] = useState("open");
  const { loading, data, error, reload } = useGet(`/v1/conflicts?status=${status}`);
  async function dismiss(id: string) {
    const r = await api(`/v1/conflicts/${id}/resolve`, { method: "POST", body: { resolution: "dismissed", note: "dismissed in Studio" } });
    if (r.ok) { onToast("Conflict dismissed (kept in history)"); reload(); } else onToast(r.error.message, "error");
  }
  return (
    <section className="space-y-2">
      <label className="text-sm">Status <select className="input ml-2 w-auto" value={status} onChange={(e) => setStatus(e.target.value)}><option value="open">open</option><option value="resolved">resolved</option></select></label>
      {loading && <div className="skeleton h-16" aria-busy="true" />}
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      {data && (
        <ul className="card divide-y text-sm">
          {data.conflicts.length === 0 && <li className="muted p-3">No {status} conflicts.</li>}
          {data.conflicts.map((c: any) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2 p-3" style={{ borderColor: "var(--line)" }}>
              <span className="badge">{c.kind}</span><span className="badge">{c.status}{c.resolution ? `: ${c.resolution}` : ""}</span>
              <span className="muted min-w-0 flex-1 truncate">{c.note ?? c.details?.note ?? `${c.fact_a} ↔ ${c.fact_b}`}</span>
              {c.status === "open" && <button className="btn btn-ghost" style={{ minHeight: 28 }} onClick={() => dismiss(c.id)}>Dismiss</button>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Facts() {
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const { loading, data, error } = useGet(`/v1/knowledge${applied ? `?q=${encodeURIComponent(applied)}` : ""}`);
  return (
    <section className="space-y-2">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(q.trim()); }}>
        <input className="input" placeholder="Search facts (e.g. capital of France)" aria-label="Search facts" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn">Search</button>
      </form>
      {loading && <div className="skeleton h-16" aria-busy="true" />}
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      {data && (
        <>
          <p className="muted text-xs">Stats: {JSON.stringify(data.stats)}</p>
          <ul className="card divide-y p-3 text-sm">
            {data.facts.length === 0 && <li className="muted">No facts match.</li>}
            {data.facts.map((f: any) => <li key={f.id} className="py-1" style={{ borderColor: "var(--line)" }}><span className="badge mr-2">{f.verification ?? f.source_type}</span>{f.statement || f.predicate}<span className="muted"> · {f.provenance ?? f.source_type} · {f.status} · conf {Number(f.confidence).toFixed(2)}</span></li>)}
          </ul>
        </>
      )}
    </section>
  );
}
