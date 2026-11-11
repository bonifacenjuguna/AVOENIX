// Browser -> Studio BFF (/api/*) -> AVOENIX API. The session cookie is HttpOnly and set by the API through the BFF.
export type ApiError = { code: string; message: string; details?: Record<string, unknown> };
export type ApiResult<T> = { ok: true; data: T; status: number; ms: number } | { ok: false; error: ApiError; status: number; ms: number };

export async function api<T = any>(path: string, init?: { method?: string; body?: unknown }): Promise<ApiResult<T>> {
  const t0 = performance.now();
  try {
    const res = await fetch(`/api${path}`, {
      method: init?.method ?? "GET",
      headers: init?.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
    });
    const ms = Math.round(performance.now() - t0);
    let json: any = null;
    try { json = await res.json(); } catch { /* non-JSON body */ }
    if (res.ok) return { ok: true, data: json as T, status: res.status, ms };
    const error: ApiError = json?.error ?? { code: "http_" + res.status, message: `Request failed (HTTP ${res.status})` };
    return { ok: false, error, status: res.status, ms };
  } catch (e) {
    return { ok: false, error: { code: "network_error", message: "Could not reach the Studio server or the AVOENIX API." }, status: 0, ms: Math.round(performance.now() - t0) };
  }
}

export type Turn = {
  turn_id: string | null; response: string; conversation_id: string | null; status: "ok" | "partial" | "error"; total_ms: number;
  trace: { stage: string; engine: string; operation: string; ms: number; ok: boolean; summary?: unknown; error?: string }[];
  understanding: Record<string, any>; reasoning: any; confidence: { band?: string; overall?: number | null; factual_support?: number | null; headline?: string; note?: string; not_evaluated?: string[] };
  emotion: any; context: any; memory: any; response_meta: Record<string, any>; errors: { stage?: string; code?: string; message?: string }[];
};
export type Conversation = { id: string; title: string | null; archived: boolean; created_at: string; updated_at: string };
export type Message = { id: string; role: "user" | "assistant"; content: string; turn_index: number; latency_ms: number | null; created_at: string };

export type DownloadResult = { ok: true; filename: string; blob: Blob; messageCount: number | null } | { ok: false; error: ApiError; status: number };

/** Fetch a file from the API (used for conversation export). Errors come back as JSON in the same shape as api(). */
export async function download(path: string): Promise<DownloadResult> {
  try {
    const res = await fetch(`/api${path}`, { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) {
      let json: any = null;
      try { json = await res.json(); } catch { /* non-JSON */ }
      return { ok: false, status: res.status, error: json?.error ?? { code: "http_" + res.status, message: `Request failed (HTTP ${res.status})` } };
    }
    const cd = res.headers.get("content-disposition") ?? "";
    const m = /filename="([A-Za-z0-9._-]+)"/.exec(cd);
    const count = res.headers.get("x-message-count");
    return { ok: true, filename: m ? m[1] : "conversation", blob: await res.blob(), messageCount: count === null ? null : Number(count) };
  } catch {
    return { ok: false, status: 0, error: { code: "network_error", message: "Could not reach the Studio server or the AVOENIX API." } };
  }
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.rel = "noopener";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
