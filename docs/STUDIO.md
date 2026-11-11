# Studio redesign (v0.0.1)

**Status: written, NOT built or rendered.** `next build`, a browser, and the React/Next type definitions were unavailable in the build environment (no network for npm). What was executed: Node unit tests of the pure-logic modules (`apps/studio/tests/lib.test.ts`, 10 PASSED) and a TypeScript syntax pass (0 syntax errors; full type-check BLOCKED BY ENVIRONMENT). Expect to fix small type or layout issues on the first real `npm install && npm run build`.

## Design system
- **Monochrome tokens** in `app/globals.css` (`--bg, --surface, --surface-2/3, --fg, --fg-2, --fg-muted, --line, --line-strong, --on-fg, --danger, --focus`). No orange or other accent; the single non-grey colour is `--danger`, used only for errors/destructive actions. Tailwind is used for layout only.
- **Light/dark**: `data-theme` on `<html>`, set before first paint by an inline script (`lib/theme.ts`), toggle in the sidebar/top bar, persisted in `localStorage` (guarded: works, unpersisted, if storage is blocked). Defaults to the OS preference.
- **Type & icons**: Inter → system sans stack, monospace for code; one inline SVG icon set (`components/Icon.tsx`, 24px grid, 1.75 stroke).
- **Motion**: short transitions only; `prefers-reduced-motion` disables them.

## Chat
User/assistant bubbles are visually distinct (inverted vs surface); Markdown subset (headings, lists, code blocks, links, inline code) rendered with React elements, never `innerHTML` (`lib/markdown.ts`); copy message (clipboard API with fallback + toast); timestamps; typing indicator; error bubbles with **Retry** and the unsent text restored to the composer; empty-state suggestions; loading skeletons; auto-scroll; `role="log"` live region.
**Sidebar**: new conversation, history grouped Today / Yesterday / Previous 7 days / Earlier, title search (titles only — message bodies are not in the list payload), active indication, per-row delete with a confirmation dialog (focus trap, Esc, focus return).
**Composer**: multiline auto-grow, Enter sends, Shift+Enter newline, IME-safe, disabled while sending, refocus after send, 8,000-character limit with a counter near the end.
**Inspector** (optional panel): status, task, timings, confidence band and factual support, claims recorded this turn (verification + provenance), trace, raw reasoning.

## Export
The menu offers Markdown, plain text and JSON for the **complete selected conversation**. The export is produced by the API (`GET /v1/conversations/{id}/export`), from all stored messages — not from what is on screen and not limited to the 500-message page (tested at 520 messages). Filenames are `<title-slug>-<id8>-<YYYYMMDD>.<ext>`. An empty conversation exports a header with "no messages" and shows a notice; failures show a specific toast. **Dependency:** the Studio needs API ≥ v0.0.1; against an older API the toast says to redeploy the API.

## Accessibility (designed in; not audited with a screen reader or axe)
Landmarks (`nav`, `aside`, `main`, `section`), `aria-current`, `aria-pressed/expanded`, labelled icon buttons, tooltips on hover **and** focus (plus `aria-label`), visible focus ring, dialog roles and focus management, `aria-live` regions, contrast chosen for ≥ 4.5:1 for muted text on both themes (computed by hand, **not** machine-verified).

## Responsive
Desktop: nav + conversation list + chat (+ inspector). Tablet/mobile: nav and conversation list become drawers; the inspector becomes a sheet. **Not verified on real devices or in a browser.**

## Other pages
Health, Memory, Learning, Evaluation were re-skinned (tokens, padding, danger colour). **Knowledge** now has Claims (filter by verification state, history), Conflicts (open/resolved, dismiss) and the raw Facts view.

## Files
`app/globals.css`, `app/layout.tsx`, `app/(studio)/{layout,chat/page,knowledge/page}.tsx`, `app/login/page.tsx`, `components/{Icon,Markdown,ThemeToggle,Toast,ConfirmDialog}.tsx`, `lib/{markdown,conversations,theme,api}.ts`, `app/api/[...path]/route.ts` (forwards `Content-Disposition`/`X-Message-Count` for export).
