import type { Conversation } from "./api";

export type Group = { label: string; items: Conversation[] };

const DAY = 86_400_000;

/** Group conversations (already newest-first) into Today / Yesterday / Previous 7 days / Earlier, using the caller's local midnight. */
export function groupConversations(list: Conversation[], now: Date = new Date()): Group[] {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const buckets: Group[] = [{ label: "Today", items: [] }, { label: "Yesterday", items: [] }, { label: "Previous 7 days", items: [] }, { label: "Earlier", items: [] }];
  for (const c of list) {
    const t = Date.parse(c.updated_at);
    const i = Number.isNaN(t) ? 3 : t >= midnight ? 0 : t >= midnight - DAY ? 1 : t >= midnight - 7 * DAY ? 2 : 3;
    buckets[i].items.push(c);
  }
  return buckets.filter((b) => b.items.length > 0);
}

export function titleOf(c: Pick<Conversation, "title" | "updated_at">): string {
  return c.title?.trim() || "New conversation";
}

/** Case-insensitive title filter. Only titles are searched: message bodies are not loaded in the list. */
export function filterConversations(list: Conversation[], q: string): Conversation[] {
  const needle = q.trim().toLowerCase();
  return needle ? list.filter((c) => titleOf(c).toLowerCase().includes(needle)) : list;
}

export function formatTime(iso: string | undefined | null, now: Date = new Date()): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
