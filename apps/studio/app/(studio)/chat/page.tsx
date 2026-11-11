"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Conversation, download, Message, saveBlob, Turn } from "@/lib/api";
import { filterConversations, formatTime, groupConversations, titleOf } from "@/lib/conversations";
import { Icon } from "@/components/Icon";
import { Markdown } from "@/components/Markdown";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";

type Row = Message | { id: string; role: "error"; content: string; created_at: string; retry?: string };
const MAX = 8000;
const PAGE_CAP = 500;     // the messages endpoint returns at most this many; export is not limited

async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through to the legacy path (non-secure context, denied permission) */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch { return false; }
}

export default function Chat() {
  const toast = useToast();
  const [convs, setConvs] = useState<Conversation[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<{ turn: Turn; roundTripMs: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [listOpen, setListOpen] = useState(false);
  const [inspector, setInspector] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [confirm, setConfirm] = useState<Conversation | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const exportRef = useRef<HTMLDivElement>(null);
  const openSeq = useRef(0);

  const loadConvs = useCallback(async () => {
    const r = await api<{ conversations: Conversation[] }>("/v1/conversations");
    if (r.ok) setConvs(r.data.conversations); else { setConvs((c) => c ?? []); setError(r.error.message); }
  }, []);
  useEffect(() => { loadConvs(); }, [loadConvs]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [rows, busy]);
  useEffect(() => {          // auto-grow the composer up to ~8 lines
    const el = area.current; if (!el) return;
    el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [text]);
  useEffect(() => {
    if (!exportOpen) return;
    const away = (e: MouseEvent) => { if (!exportRef.current?.contains(e.target as Node)) setExportOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setExportOpen(false); };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [exportOpen]);

  async function open(id: string | null) {
    const seq = ++openSeq.current;
    setActive(id); setLast(null); setError(null); setListOpen(false);
    if (!id) { setRows([]); setTimeout(() => area.current?.focus(), 0); return; }
    setRows([]); setLoadingMsgs(true);
    const r = await api<{ messages: Message[] }>(`/v1/conversations/${id}/messages`);
    if (seq !== openSeq.current) return;           // a newer selection won the race
    setLoadingMsgs(false);
    if (r.ok) setRows(r.data.messages); else setError(r.error.message);
  }

  async function send(override?: string) {
    const t = (override ?? text).trim();
    if (!t || busy) return;
    setBusy(true); setError(null); setText("");
    const now = new Date().toISOString();
    setRows((r) => [...r.filter((x) => x.role !== "error"), { id: "pending-" + Date.now(), role: "user", content: t, turn_index: r.length, latency_ms: null, created_at: now }]);
    const res = await api<Turn>("/v1/chat", { method: "POST", body: { text: t, conversation_id: active } });
    setBusy(false);
    if (!res.ok) {
      if (res.status === 401) { window.location.assign("/login"); return; }
      setRows((r) => [...r, { id: "err-" + Date.now(), role: "error", content: res.error.message, created_at: new Date().toISOString(), retry: t }]);
      setText((cur) => cur || t);                  // error recovery: the message is back in the composer, nothing is lost
      setTimeout(() => area.current?.focus(), 0);
      return;
    }
    const turn = res.data;
    setLast({ turn, roundTripMs: res.ms });
    setRows((r) => [...r, { id: turn.turn_id ?? "a-" + Date.now(), role: "assistant", content: turn.response, turn_index: r.length, latency_ms: turn.total_ms, created_at: new Date().toISOString() }]);
    if (turn.conversation_id && turn.conversation_id !== active) setActive(turn.conversation_id);
    loadConvs();
    setTimeout(() => area.current?.focus(), 0);
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
  }

  async function doDelete() {
    if (!confirm) return;
    setDeleting(true);
    const r = await api(`/v1/conversations/${confirm.id}`, { method: "DELETE" });
    setDeleting(false);
    if (r.ok) { if (active === confirm.id) await open(null); toast("Conversation deleted"); loadConvs(); } else toast(r.error.message, "error");
    setConfirm(null);
  }

  async function copy(m: Row) {
    const ok = await copyText(m.content);
    if (ok) { setCopied(m.id); setTimeout(() => setCopied((c) => (c === m.id ? null : c)), 1500); toast("Copied to clipboard"); } else toast("Copy failed — select the text and copy manually", "error");
  }

  async function exportAs(fmt: "md" | "txt" | "json") {
    setExportOpen(false);
    if (!active) { toast("Nothing to export yet — send a message first", "error"); return; }
    setExporting(true);
    const r = await download(`/v1/conversations/${active}/export?format=${fmt}`);
    setExporting(false);
    if (!r.ok) {
      if (r.status === 404 && r.error.code === "not_found") toast("Export failed: conversation not found (it may have been deleted)", "error");
      else if (r.status === 404 || r.status === 405) toast("Export needs AVOENIX API v0.0.1 (GET /v1/conversations/{id}/export). Redeploy the API.", "error");
      else toast(`Export failed: ${r.error.message}`, "error");
      return;
    }
    if (r.messageCount === 0) toast("This conversation is empty — exported the header only");
    saveBlob(r.blob, r.filename);
    if (r.messageCount !== 0) toast(`Exported ${r.messageCount ?? "all"} messages as ${r.filename}`);
  }

  const groups = useMemo(() => groupConversations(filterConversations(convs ?? [], query)), [convs, query]);
  const activeConv = convs?.find((c) => c.id === active) ?? null;
  const heading = activeConv ? titleOf(activeConv) : active ? "Conversation" : "New conversation";
  const empty = rows.length === 0 && !loadingMsgs;
  const left = text.length > MAX - 400 ? MAX - text.length : null;

  const list = (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <button className="btn" onClick={() => open(null)}><Icon name="plus" size={16} />New conversation</button>
      <div className="relative">
        <span className="pointer-events-none absolute left-2.5 top-2.5 muted"><Icon name="search" size={16} /></span>
        <input className="input pl-8" placeholder="Search titles" aria-label="Search conversation titles" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-auto">
        {convs === null && <div className="space-y-2 pt-2" aria-busy="true">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-8" />)}</div>}
        {convs !== null && groups.length === 0 && <p className="muted px-1 pt-3 text-sm">{query ? "No conversations match." : "No conversations yet."}</p>}
        {groups.map((g) => (
          <div key={g.label} className="mb-3">
            <h3 className="muted px-2 pb-1 pt-2 text-xs font-medium uppercase tracking-wide">{g.label}</h3>
            <ul className="flex flex-col gap-0.5">
              {g.items.map((c) => (
                <li key={c.id} className="conv-row" data-active={c.id === active}>
                  <button className="min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-sm" onClick={() => open(c.id)} aria-current={c.id === active ? "true" : undefined} title={titleOf(c)}>{titleOf(c)}</button>
                  <button className="icon-btn conv-actions" aria-label={`Delete conversation ${titleOf(c)}`} data-tip="Delete" onClick={() => setConfirm(c)}><Icon name="trash" size={16} /></button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  );

  return (
    <div className="flex h-full min-h-0">
      {/* Conversation list: column on desktop, drawer on small screens */}
      <aside className="hidden w-64 shrink-0 border-r p-3 lg:block" style={{ borderColor: "var(--line)" }}>{list}</aside>
      {listOpen && (
        <div className="fixed inset-0 z-30 lg:hidden" onClick={() => setListOpen(false)} style={{ background: "color-mix(in srgb, var(--bg) 70%, transparent)" }}>
          <div className="pop absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r p-3" style={{ background: "var(--surface)", borderColor: "var(--line)" }} onClick={(e) => e.stopPropagation()}>{list}</div>
        </div>
      )}

      <section className="flex min-w-0 flex-1 flex-col" aria-label="Conversation">
        <header className="flex items-center gap-2 border-b px-3 py-2" style={{ borderColor: "var(--line)" }}>
          <button className="icon-btn lg:hidden" aria-label="Show conversations" data-tip="Conversations" onClick={() => setListOpen(true)}><Icon name="chat" /></button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{heading}</h1>
          <div className="relative" ref={exportRef}>
            <button className="btn btn-ghost" aria-haspopup="menu" aria-expanded={exportOpen} disabled={exporting || !active} onClick={() => setExportOpen((o) => !o)} title={active ? "Export the complete conversation" : "Send a message to enable export"}>
              <Icon name="download" size={16} />{exporting ? "Exporting…" : "Export"}
            </button>
            {exportOpen && (
              <div role="menu" className="card pop absolute right-0 z-20 mt-1 w-52 p-1" style={{ boxShadow: "var(--shadow)" }}>
                {([["md", "Markdown (.md)"], ["txt", "Plain text (.txt)"], ["json", "JSON (.json)"]] as const).map(([f, label]) => (
                  <button key={f} role="menuitem" className="nav-link w-full" onClick={() => exportAs(f)}><Icon name="file" size={16} />{label}</button>
                ))}
                <p className="muted px-2 py-1 text-xs">Exports every message, not just those on screen.</p>
              </div>
            )}
          </div>
          <button className="icon-btn" aria-label="Toggle turn inspector" aria-pressed={inspector} data-tip="Inspector" data-tip-pos="left" onClick={() => setInspector((v) => !v)}><Icon name="info" /></button>
        </header>

        <div className="min-h-0 flex-1 overflow-auto px-3 py-4 sm:px-6" role="log" aria-live="polite" aria-label="Messages">
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {loadingMsgs && <div className="space-y-3" aria-busy="true"><div className="skeleton h-12 w-2/3" /><div className="skeleton ml-auto h-10 w-1/2" /><div className="skeleton h-16 w-3/4" /></div>}
            {empty && (
              <div className="mx-auto mt-16 max-w-md text-center">
                <h2 className="text-lg font-semibold tracking-tight">Ask AVOENIX something</h2>
                <p className="muted mt-1 text-sm">It reasons with explicit rules and stored knowledge. It will say when it doesn’t know, and it won’t treat what you tell it as fact without checking.</p>
                <div className="mt-4 flex flex-col gap-2">
                  {["What is the capital of Kenya?", "John is older than Peter. Peter is older than David. Who is the youngest?"].map((s) => (
                    <button key={s} className="btn btn-ghost text-left" onClick={() => { setText(s); area.current?.focus(); }}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {rows.length >= PAGE_CAP && <p className="muted text-center text-xs">Showing the first {PAGE_CAP} messages. Export includes the complete conversation.</p>}
            {rows.map((m) => (
              <article key={m.id} className={`msg flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`} aria-label={m.role === "user" ? "You" : m.role === "error" ? "Error" : "AVOENIX"}>
                <div className="muted mb-1 flex items-center gap-2 px-1 text-xs">
                  <span className="font-medium">{m.role === "user" ? "You" : m.role === "error" ? "Error" : "AVOENIX"}</span>
                  {m.created_at && <time dateTime={m.created_at}>{formatTime(m.created_at)}</time>}
                </div>
                <div className={`max-w-[min(100%,44rem)] px-3.5 py-2.5 text-sm ${m.role === "user" ? "bubble-user" : m.role === "error" ? "bubble-error" : "bubble-assistant"}`}>
                  {m.role === "error" ? <p role="alert">{m.content}</p> : <Markdown text={m.content} />}
                </div>
                <div className="msg-actions mt-1 flex items-center gap-1">
                  {m.role !== "error" ? (
                    <button className="icon-btn" aria-label="Copy message" data-tip={copied === m.id ? "Copied" : "Copy"} onClick={() => copy(m)}><Icon name={copied === m.id ? "check" : "copy"} size={16} /></button>
                  ) : "retry" in m && m.retry ? (
                    <button className="btn btn-ghost" style={{ minHeight: 28 }} onClick={() => send(m.retry)} disabled={busy}>Retry</button>
                  ) : null}
                </div>
              </article>
            ))}
            {busy && <div className="bubble-assistant w-fit px-4 py-3" role="status" aria-label="AVOENIX is working"><div className="dots" aria-hidden="true"><span /><span /><span /></div></div>}
            <div ref={bottom} />
          </div>
        </div>

        <div className="border-t px-3 py-3 sm:px-6" style={{ borderColor: "var(--line)" }}>
          <form className="mx-auto max-w-3xl" onSubmit={(e) => { e.preventDefault(); send(); }}>
            {error && <p role="alert" className="mb-2 text-sm" style={{ color: "var(--danger)" }}>{error}</p>}
            <div className="card flex items-end gap-2 p-2" style={{ borderColor: "var(--line-strong)" }}>
              <textarea ref={area} className="max-h-[200px] min-h-[36px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none" rows={1} value={text} onChange={(e) => setText(e.target.value.slice(0, MAX))} onKeyDown={onKey}
                        placeholder="Message AVOENIX (English) — Enter to send, Shift+Enter for a new line" aria-label="Message" disabled={busy} maxLength={MAX} autoFocus />
              <button className="btn" type="submit" disabled={busy || !text.trim()} aria-label="Send message"><Icon name="send" size={16} />{busy ? "Working" : "Send"}</button>
            </div>
            {left !== null && <p className="muted mt-1 text-right text-xs">{left} characters left</p>}
          </form>
        </div>
      </section>

      {inspector && (
        <aside className="hidden w-80 shrink-0 overflow-auto border-l p-3 text-sm xl:block" style={{ borderColor: "var(--line)" }} aria-label="Turn inspector"><Inspector last={last} /></aside>
      )}
      {inspector && (
        <div className="fixed inset-0 z-30 xl:hidden" style={{ background: "color-mix(in srgb, var(--bg) 70%, transparent)" }} onClick={() => setInspector(false)}>
          <aside className="pop absolute inset-y-0 right-0 w-[22rem] max-w-[90vw] overflow-auto border-l p-3 text-sm" style={{ background: "var(--surface)", borderColor: "var(--line)" }} onClick={(e) => e.stopPropagation()} aria-label="Turn inspector">
            <div className="mb-2 flex justify-end"><button className="icon-btn" aria-label="Close inspector" onClick={() => setInspector(false)}><Icon name="x" /></button></div>
            <Inspector last={last} />
          </aside>
        </div>
      )}

      <ConfirmDialog open={!!confirm} title="Delete this conversation?" body={confirm ? `“${titleOf(confirm)}” and its stored messages will be permanently deleted. This cannot be undone.` : ""} confirmLabel="Delete" busy={deleting} onConfirm={doDelete} onCancel={() => !deleting && setConfirm(null)} />
    </div>
  );
}

function Inspector({ last }: { last: { turn: Turn; roundTripMs: number } | null }) {
  if (!last) return <><h2 className="mb-2 font-semibold">Last turn</h2><p className="muted">Nothing yet. Values here are measured, never simulated.</p></>;
  const t = last.turn;
  const claims = (t.memory?.stored_facts ?? []).filter((f: any) => f?.claim_type === "world");
  return (
    <div className="space-y-3">
      <h2 className="font-semibold">Last turn</h2>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="muted">Status</dt><dd>{t.status}</dd>
        <dt className="muted">Task</dt><dd>{t.understanding?.task ?? "—"}</dd>
        <dt className="muted">Engine</dt><dd>{t.total_ms.toFixed(1)} ms</dd>
        <dt className="muted">Round trip</dt><dd>{last.roundTripMs} ms</dd>
        <dt className="muted">Confidence</dt><dd>{t.confidence?.band ?? "not_evaluated"}{t.confidence?.overall != null && <> ({t.confidence.overall})</>}</dd>
        {t.confidence?.factual_support != null && <><dt className="muted">Factual support</dt><dd>{t.confidence.factual_support}</dd></>}
      </dl>
      <p className="muted text-xs">{t.confidence?.note ?? "Confidence is an evidence-support score, not a probability."}</p>
      {claims.length > 0 && (
        <div>
          <h3 className="mb-1 font-medium">Claims recorded this turn</h3>
          <ul className="space-y-1">
            {claims.map((f: any, i: number) => <li key={i}><span className="badge mr-1">{f.verification}</span><span className="muted">{f.provenance}</span></li>)}
          </ul>
        </div>
      )}
      {t.errors.length > 0 && <div style={{ color: "var(--danger)" }}><b>Errors</b>{t.errors.map((e, i) => <p key={i}>{e.stage}: {e.code} {e.message}</p>)}</div>}
      <details><summary className="cursor-pointer">Pipeline trace ({t.trace.length} stages)</summary>
        <table className="mt-1 w-full text-xs"><tbody>{t.trace.map((s, i) => <tr key={i}><td>{s.stage}</td><td className="muted">{s.operation}</td><td className="text-right">{s.ms.toFixed(2)} ms</td><td>{s.ok ? "✓" : "✗"}</td></tr>)}</tbody></table>
      </details>
      <details><summary className="cursor-pointer">Raw reasoning</summary><pre className="mt-1 max-h-64 overflow-auto text-xs">{JSON.stringify(t.reasoning, null, 1)}</pre></details>
    </div>
  );
}
