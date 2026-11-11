"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Status, useGet } from "@/components/Panel";

export default function Learning() {
  const { loading, data, error, reload } = useGet("/v1/learning/history");
  const [msg, setMsg] = useState<string | null>(null);
  async function revert(id: string) {
    const r = await api(`/v1/learning/${id}/revert`, { method: "POST", body: {} });
    setMsg(r.ok ? "Reverted and verified." : `${r.error.code}: ${r.error.message}`);
    reload();
  }
  return (
    <div className="mx-auto max-w-5xl space-y-3 p-4 sm:p-6">
      <h1 className="text-xl font-semibold">Learning</h1>
      <Status level="partial">Shows verified, reversible updates (preferences, corrections, strategy switches). Approval of project-wide knowledge has an API but no Studio UI yet.</Status>
      {msg && <p role="status" className="text-sm">{msg}</p>}
      {loading && <p className="muted">Loading…</p>}
      {error && <p role="alert" style={{ color: "var(--danger)" }}>{error}</p>}
      {data && (
        <ul className="card divide-y p-3 text-sm">
          {data.records.length === 0 && <li className="muted">No learning records yet.</li>}
          {data.records.map((r: any) => (
            <li key={r.id} className="flex items-center justify-between gap-2 py-1">
              <span><span className="badge mr-2">{r.kind}</span><span className="badge mr-2">{r.status}</span>{JSON.stringify(r.proposal?.change ?? r.proposal?.statement ?? r.proposal)}</span>
              {r.status === "applied" && <button className="underline" onClick={() => revert(r.id)}>Revert</button>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
