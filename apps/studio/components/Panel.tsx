"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function Status({ level, children }: { level: "implemented" | "partial" | "not_implemented" | "not_evaluated" | "experimental"; children?: React.ReactNode }) {
  const label = { implemented: "implemented", partial: "partially implemented", not_implemented: "not implemented", not_evaluated: "not evaluated", experimental: "experimental" }[level];
  return <p className="card mb-3 p-3 text-sm"><span className="badge mr-2">{label}</span>{children}</p>;
}

export function useGet<T = any>(path: string | null) {
  const [state, set] = useState<{ loading: boolean; data?: T; error?: string }>({ loading: !!path });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    let live = true;
    set({ loading: true });
    api<T>(path).then((r) => { if (live) set(r.ok ? { loading: false, data: r.data } : { loading: false, error: `${r.error.code}: ${r.error.message}` }); });
    return () => { live = false; };
  }, [path, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}
