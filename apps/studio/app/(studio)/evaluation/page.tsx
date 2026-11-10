"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Status, useGet } from "@/components/Panel";

export default function Evaluation() {
  const runs = useGet("/v1/evaluation/runs");
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true); setError(null);
    const r = await api("/v1/evaluation/run", { method: "POST", body: {} });
    setRunning(false);
    if (r.ok) { setReport(r.data); runs.reload(); } else setError(`${r.error.code}: ${r.error.message}`);
  }
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">Evaluation</h1>
      <Status level="partial">Runs the bundled developer-authored dataset against this deployment. Targets are development goals, not achievements; the dataset is small and does not generalise.</Status>
      <button className="btn" onClick={run} disabled={running}>{running ? "Running…" : "Run evaluation now"}</button>
      {error && <p role="alert" className="text-red-600">{error}</p>}
      {report && (
        <div className="card space-y-1 p-3 text-sm">
          <p>Overall: <b>{report.summary.overall.passed}/{report.summary.overall.total}</b> · splits: {JSON.stringify(report.summary.by_split)}</p>
          {Object.entries(report.summary.metrics).map(([k, v]: any) => <p key={k}>{k}: {v.passed}/{v.total} (target {v.target}) — <b>{v.status}</b></p>)}
          {report.failures.length > 0 && <details><summary className="cursor-pointer">{report.failures.length} failing cases</summary><ul className="text-xs">{report.failures.map((f: any) => <li key={f.id}>{f.id}: {f.reasons.join("; ")}</li>)}</ul></details>}
        </div>
      )}
      <h2 className="font-semibold">Stored runs</h2>
      {runs.loading ? <p className="muted">Loading…</p> : runs.error ? <p className="text-red-600">{runs.error}</p> : (
        <ul className="card divide-y p-3 text-sm">
          {runs.data.runs.length === 0 && <li className="muted">No stored runs.</li>}
          {runs.data.runs.map((r: any) => <li key={r.id} className="py-1">{r.started_at} · {r.suite} · {r.summary?.overall?.passed}/{r.summary?.overall?.total}</li>)}
        </ul>
      )}
    </div>
  );
}
