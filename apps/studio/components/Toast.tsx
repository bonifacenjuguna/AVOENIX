"use client";
import { createContext, useCallback, useContext, useRef, useState } from "react";

type T = { id: number; msg: string; kind: "ok" | "error" };
const Ctx = createContext<(msg: string, kind?: "ok" | "error") => void>(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<T[]>([]);
  const n = useRef(0);
  const push = useCallback((msg: string, kind: "ok" | "error" = "ok") => {
    const id = ++n.current;
    setItems((x) => [...x.slice(-2), { id, msg, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 6000 : 2600);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2 px-4" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="card pop pointer-events-auto px-3 py-2 text-sm" style={{ boxShadow: "var(--shadow)", borderColor: t.kind === "error" ? "var(--danger)" : undefined, color: t.kind === "error" ? "var(--danger)" : undefined }}>{t.msg}</div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
