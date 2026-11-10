"use client";
import { useState } from "react";
import { Status, useGet } from "@/components/Panel";

export default function Knowledge() {
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const { loading, data, error } = useGet(`/v1/knowledge${applied ? `?q=${encodeURIComponent(applied)}` : ""}`);
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">Knowledge</h1>
      <Status level="partial">Read-only view. The curated seed is small (a few dozen facts); anything else comes from what you told the system.</Status>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(q.trim()); }}>
        <input className="input" placeholder="Search facts (e.g. capital of France)" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn">Search</button>
      </form>
      {loading && <p className="muted">Loading…</p>}
      {error && <p role="alert" className="text-red-600">{error}</p>}
      {data && (
        <>
          <p className="muted text-xs">Stats: {JSON.stringify(data.stats)}</p>
          <ul className="card divide-y p-3 text-sm" style={{ borderColor: "var(--line)" }}>
            {data.facts.length === 0 && <li className="muted">No facts match.</li>}
            {data.facts.map((f: any) => <li key={f.id} className="py-1"><span className="badge mr-2">{f.source_type}</span>{f.statement || f.predicate}<span className="muted"> · {f.status} · conf {Number(f.confidence).toFixed(2)}</span></li>)}
          </ul>
        </>
      )}
    </div>
  );
}
