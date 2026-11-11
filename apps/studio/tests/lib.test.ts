// Run: node --experimental-strip-types --test tests/   (Node >= 22.6). Pure-logic tests only; component rendering is NOT covered (see docs/TESTING.md).
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseBlocks, parseInline, safeHref } from "../lib/markdown.ts";
import { filterConversations, formatTime, groupConversations, titleOf } from "../lib/conversations.ts";
import { NO_FLASH_SCRIPT, resolveTheme } from "../lib/theme.ts";

const conv = (id: string, title: string | null, updated_at: string) => ({ id, title, archived: false, created_at: updated_at, updated_at });

test("markdown: headings, lists, code fences, paragraphs", () => {
  const b = parseBlocks("# Title\n\nHello **world** and `code`.\n\n- a\n- b\n\n1. one\n2. two\n\n```py\nprint(1)\n```\n");
  assert.deepEqual(b.map((x) => x.t), ["h", "p", "ul", "ol", "code"]);
  const code = b[4] as any;
  assert.equal(code.lang, "py"); assert.equal(code.v, "print(1)");
  assert.equal((b[2] as any).items.length, 2);
});

test("markdown: unterminated fence runs to the end, content is kept", () => {
  const b = parseBlocks("```\nabc\ndef");
  assert.equal(b.length, 1); assert.equal((b[0] as any).v, "abc\ndef");
});

test("markdown: code content is never parsed as markdown", () => {
  const b = parseBlocks("```\n**not bold** <script>\n```");
  assert.equal((b[0] as any).v, "**not bold** <script>");
});

test("markdown: inline formatting and html stays text", () => {
  const i = parseInline("a **b** *c* `d` <img src=x onerror=alert(1)>");
  assert.deepEqual(i.map((x) => x.t), ["text", "strong", "text", "em", "text", "code", "text"]);
  assert.ok((i[6] as any).v.includes("<img"));            // rendered as text by React, never as markup
});

test("markdown: only http(s)/mailto links are linkified", () => {
  assert.equal(safeHref("https://example.com/a?b=1"), "https://example.com/a?b=1");
  assert.equal(safeHref("javascript:alert(1)"), null);
  assert.equal(safeHref("data:text/html,x"), null);
  const i = parseInline("[x](javascript:alert(1))");
  assert.ok(!i.some((n) => n.t === "link"));            // unsafe target: link text kept, no anchor produced
});

test("markdown: empty and whitespace input", () => {
  assert.deepEqual(parseBlocks(""), []);
  assert.deepEqual(parseBlocks("  \n\n "), []);
});

test("conversations: grouping by local day, empty groups dropped", () => {
  const now = new Date(2026, 10, 10, 15, 0, 0);
  const list = [conv("a", "A", new Date(2026, 10, 10, 9).toISOString()), conv("b", "B", new Date(2026, 10, 9, 20).toISOString()),
                conv("c", "C", new Date(2026, 10, 6).toISOString()), conv("d", null, new Date(2026, 9, 1).toISOString()), conv("e", "E", "garbage")];
  const g = groupConversations(list as any, now);
  assert.deepEqual(g.map((x) => [x.label, x.items.map((i) => i.id)]), [["Today", ["a"]], ["Yesterday", ["b"]], ["Previous 7 days", ["c"]], ["Earlier", ["d", "e"]]]);
  assert.deepEqual(groupConversations([], now), []);
});

test("conversations: title fallback and filter", () => {
  assert.equal(titleOf({ title: "  ", updated_at: "" }), "New conversation");
  const list = [conv("a", "Capital of Kenya", "2026-01-01T00:00:00Z"), conv("b", null, "2026-01-01T00:00:00Z")] as any;
  assert.deepEqual(filterConversations(list, "KENYA").map((c) => c.id), ["a"]);
  assert.equal(filterConversations(list, "  ").length, 2);
  assert.equal(filterConversations(list, "zzz").length, 0);
});

test("time formatting tolerates missing/invalid values", () => {
  assert.equal(formatTime(""), ""); assert.equal(formatTime("nope"), ""); assert.equal(formatTime(null), "");
  assert.notEqual(formatTime("2026-01-01T10:00:00Z"), "");
});

test("theme: stored choice wins, system preference otherwise, junk ignored", () => {
  assert.equal(resolveTheme("light", true), "light"); assert.equal(resolveTheme("dark", false), "dark");
  assert.equal(resolveTheme(null, true), "dark"); assert.equal(resolveTheme("purple", false), "light");
  assert.ok(NO_FLASH_SCRIPT.includes("data-theme") && NO_FLASH_SCRIPT.includes("avoenix-theme"));
});
