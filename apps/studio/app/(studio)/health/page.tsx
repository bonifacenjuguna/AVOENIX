"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type EngineHealth = { key: string; status: string; detail: string; metrics: { calls: number; errors: number; avg_ms: number | null; max_ms: number | null; last_error: string | null } };

export default function Health() {
  const [d, setD] = useState<any>(null);
  const [readyz, setReadyz] = useState<{ status: number; ms: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    const [diag, ready] = await Promise.all([api("/v1/diagnostics"), api("/v1/version")]);
    setLoading(false);
    setReadyz({ status: ready.status, ms: ready.ms });
    if (diag.ok) setD({ ...diag.data, roundTripMs: diag.ms }); else { setD(null); setError(`${diag.error.code}: ${diag.error.message}`); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Health & diagnostics</h1>
        <button className="btn" onClick={load} disabled={loading}>{loading ? "Checking…" : "Re-run checks"}</button>
      </div>
      {error && <p role="alert" className="card border-red-500 p-3 text-red-600">Backend unreachable or refused: {error}</p>}
      {d && (
        <>
          <div className="card grid gap-2 p-3 text-sm sm:grid-cols-4">
            <div><div className="muted">Platform</div><b>{d.version.platform}</b></div>
            <div><div className="muted">API / ACR / DB schema</div><b>{d.version.api} / {d.version.acr_schema} / {d.version.database_schema}</b></div>
            <div><div className="muted">Storage</div><b>{d.storage.ok ? "ok" : "FAILED"}</b> <span className="muted">{d.storage.detail}</span></div>
            <div><div className="muted">Round trip (this page)</div><b>{d.roundTripMs} ms</b> · uptime {d.uptime_s}s</div>
          </div>
          <div className="card overflow-x-auto p-3">
            <table className="w-full text-sm">
              <thead><tr className="muted text-left"><th>Engine</th><th>Status</th><th>Self-check</th><th className="text-right">Calls</th><th className="text-right">Errors</th><th className="text-right">Avg ms</th></tr></thead>
              <tbody>
                {d.engines.map((e: EngineHealth) => (
                  <tr key={e.key} className="border-t" style={{ borderColor: "var(--line)" }}>
                    <td className="py-1 font-medium">{e.key}</td>
                    <td className={e.status === "ok" ? "" : "text-red-600"}>{e.status}</td>
                    <td className="muted">{e.detail}</td>
                    <td className="text-right">{e.metrics.calls}</td><td className="text-right">{e.metrics.errors}</td>
                    <td className="text-right">{e.metrics.avg_ms ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted mt-2 text-xs">Metrics count calls since the API process started. “—” means no calls recorded, not zero latency.</p>
          </div>
          <div className="card p-3 text-sm">
            <h2 className="mb-1 font-semibold">Studio milestones (honest status)</h2>
            <ul className="list-disc pl-5">{Object.entries(d.implemented_milestones).map(([k, v]) => <li key={k}>Milestone {k}: {String(v)}</li>)}</ul>
            <p className="muted mt-2 text-xs">Audit-record write failures since start: {d.audit_write_failures}.</p>
          </div>
        </>
      )}
      {readyz && <p className="muted text-xs">Version endpoint: HTTP {readyz.status} in {readyz.ms} ms.</p>}
    </div>
  );
}
