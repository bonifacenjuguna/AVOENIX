"use client";
import { useState } from "react";
import { Status, useGet } from "@/components/Panel";

export default function Memory() {
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const { loading, data, error } = useGet(`/v1/memory${applied ? `?q=${encodeURIComponent(applied)}` : ""}`);
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">Memory</h1>
      <Status level="partial">Read-only inspection of your own memory (admin scope). Editing and deletion are not implemented in the Studio yet.</Status>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(q.trim()); }}>
        <input className="input" placeholder="Search memory (ranked recall)" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn">Search</button>
      </form>
      {loading && <p className="muted">Loading…</p>}
      {error && <p role="alert" className="text-red-600">{error}</p>}
      {data && (
        <>
          <div className="card p-3 text-sm"><b>Preferences</b><pre className="mt-1 text-xs">{Object.keys(data.preferences).length ? JSON.stringify(data.preferences, null, 1) : "none stored"}</pre></div>
          <div className="card p-3 text-sm"><b>{applied ? "Recall results" : "Recent memories"}</b>
            {data.items.length === 0 ? <p className="muted">Nothing found.</p> : <ul className="mt-1 space-y-1">{data.items.map((m: any) => <li key={m.id}><span className="badge mr-2">{m.category}</span>{m.content}{m.score !== undefined && <span className="muted"> · score {Number(m.score).toFixed(2)}</span>}</li>)}</ul>}
          </div>
        </>
      )}
    </div>
  );
}
