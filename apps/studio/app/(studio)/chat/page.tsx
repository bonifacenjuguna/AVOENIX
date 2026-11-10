"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, Conversation, Message, Turn } from "@/lib/api";

type Row = Message | { id: string; role: "error"; content: string };

export default function Chat() {
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<{ turn: Turn; roundTripMs: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const loadConvs = useCallback(async () => {
    const r = await api<{ conversations: Conversation[] }>("/v1/conversations");
    if (r.ok) setConvs(r.data.conversations); else setError(r.error.message);
  }, []);
  useEffect(() => { loadConvs(); }, [loadConvs]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [rows]);

  async function open(id: string | null) {
    setActive(id); setLast(null); setError(null);
    if (!id) { setRows([]); return; }
    const r = await api<{ messages: Message[] }>(`/v1/conversations/${id}/messages`);
    if (r.ok) setRows(r.data.messages); else setError(r.error.message);
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true); setError(null); setText("");
    setRows((r) => [...r, { id: "pending-" + Date.now(), role: "user", content: t, turn_index: r.length, latency_ms: null, created_at: "" }]);
    const res = await api<Turn>("/v1/chat", { method: "POST", body: { text: t, conversation_id: active } });
    setBusy(false);
    if (!res.ok) {
      setRows((r) => [...r, { id: "err-" + Date.now(), role: "error", content: `${res.error.code}: ${res.error.message}` }]);
      if (res.status === 401) window.location.assign("/login");
      return;
    }
    const turn = res.data;
    setLast({ turn, roundTripMs: res.ms });
    setRows((r) => [...r, { id: turn.turn_id ?? "a-" + Date.now(), role: "assistant", content: turn.response, turn_index: r.length, latency_ms: turn.total_ms, created_at: "" }]);
    if (turn.conversation_id && turn.conversation_id !== active) { setActive(turn.conversation_id); }
    loadConvs();
  }

  async function remove(id: string) {
    if (!confirm("Delete this conversation and its stored messages?")) return;
    const r = await api(`/v1/conversations/${id}`, { method: "DELETE" });
    if (r.ok) { if (active === id) open(null); loadConvs(); } else setError(r.error.message);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[14rem_1fr_20rem]">
      <section className="card p-3">
        <button className="btn mb-2 w-full" onClick={() => open(null)}>New conversation</button>
        <ul className="flex max-h-72 flex-col gap-1 overflow-auto text-sm lg:max-h-[70vh]">
          {convs.length === 0 && <li className="muted">No conversations yet.</li>}
          {convs.map((c) => (
            <li key={c.id} className="flex items-center gap-1">
              <button className={`min-w-0 flex-1 truncate rounded px-2 py-1 text-left ${c.id === active ? "font-semibold" : ""}`} style={c.id === active ? { background: "var(--bg)" } : undefined} onClick={() => open(c.id)}>
                {c.title || new Date(c.updated_at).toLocaleString()}
              </button>
              <button aria-label="Delete conversation" className="muted px-1" onClick={() => remove(c.id)}>×</button>
            </li>
          ))}
        </ul>
      </section>

      <section className="card flex min-h-[60vh] flex-col p-3">
        <div className="flex-1 space-y-3 overflow-auto">
          {rows.length === 0 && <p className="muted text-sm">Say something. Try: “John is older than Peter. Peter is older than David. Who is the youngest?”</p>}
          {rows.map((m) => (
            <div key={m.id} className={m.role === "user" ? "text-right" : ""}>
              <div className={`inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-left text-sm ${m.role === "error" ? "border border-red-500 text-red-600" : ""}`} style={m.role === "user" ? { background: "var(--accent)", color: "#fff" } : m.role === "assistant" ? { background: "var(--bg)" } : undefined}>
                {m.content}
              </div>
            </div>
          ))}
          {busy && <p className="muted text-sm">Working…</p>}
          <div ref={bottom} />
        </div>
        {error && <p role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
        <form onSubmit={send} className="mt-3 flex gap-2">
          <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Message AVOENIX (English)" maxLength={8000} aria-label="Message" />
          <button className="btn" disabled={busy || !text.trim()}>Send</button>
        </form>
      </section>

      <section className="card p-3 text-sm">
        <h2 className="mb-2 font-semibold">Last turn</h2>
        {!last ? <p className="muted">Nothing yet. Values below are measured, never simulated.</p> : (
          <div className="space-y-2">
            <p>Status: <b>{last.turn.status}</b> · task: <b>{last.turn.understanding?.task ?? "—"}</b></p>
            <p>Engine time: <b>{last.turn.total_ms.toFixed(1)} ms</b> · round trip: <b>{last.roundTripMs} ms</b></p>
            <p>Confidence band: <b>{last.turn.confidence?.band ?? "not_evaluated"}</b>{last.turn.confidence?.overall != null && <> ({last.turn.confidence.overall})</>}</p>
            <p className="muted text-xs">{last.turn.confidence?.note ?? "Confidence is an evidence-support score, not a probability."}</p>
            {last.turn.errors.length > 0 && <div className="text-red-600"><b>Errors</b>{last.turn.errors.map((e, i) => <p key={i}>{e.stage}: {e.code} {e.message}</p>)}</div>}
            <details><summary className="cursor-pointer">Pipeline trace ({last.turn.trace.length} stages)</summary>
              <table className="mt-1 w-full text-xs"><tbody>
                {last.turn.trace.map((s, i) => <tr key={i}><td>{s.stage}</td><td className="muted">{s.operation}</td><td className="text-right">{s.ms.toFixed(2)} ms</td><td>{s.ok ? "✓" : "✗"}</td></tr>)}
              </tbody></table>
            </details>
            <details><summary className="cursor-pointer">Raw reasoning</summary><pre className="mt-1 max-h-64 overflow-auto text-xs">{JSON.stringify(last.turn.reasoning, null, 1)}</pre></details>
          </div>
        )}
      </section>
    </div>
  );
}
