// Small, dependency-free Markdown subset -> typed tree. Rendering happens in components/Markdown.tsx with React elements only
// (no innerHTML), so assistant/user text can never inject markup. Links are limited to http(s)/mailto.
export type Inline =
  | { t: "text"; v: string }
  | { t: "code"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "link"; href: string; c: Inline[] };

export type Block =
  | { t: "p"; c: Inline[] }
  | { t: "h"; level: 1 | 2 | 3 | 4; c: Inline[] }
  | { t: "ul"; items: Inline[][] }
  | { t: "ol"; items: Inline[][]; start: number }
  | { t: "code"; lang: string; v: string }
  | { t: "quote"; c: Inline[] }
  | { t: "hr" };

export function safeHref(href: string): string | null {
  const h = href.trim();
  return /^(https?:\/\/|mailto:)[^\s<>"']+$/i.test(h) ? h : null;
}

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let i = 0, buf = "";
  const flush = () => { if (buf) { out.push({ t: "text", v: buf }); buf = ""; } };
  while (i < src.length) {
    const ch = src[i];
    if (ch === "`") {
      const j = src.indexOf("`", i + 1);
      if (j > i) { flush(); out.push({ t: "code", v: src.slice(i + 1, j) }); i = j + 1; continue; }
    }
    if ((ch === "*" && src[i + 1] === "*") || (ch === "_" && src[i + 1] === "_")) {
      const m = ch + ch, j = src.indexOf(m, i + 2);
      if (j > i + 2) { flush(); out.push({ t: "strong", c: parseInline(src.slice(i + 2, j)) }); i = j + 2; continue; }
    }
    if (ch === "*" || (ch === "_" && (i === 0 || /\W/.test(src[i - 1])))) {
      const j = src.indexOf(ch, i + 1);
      if (j > i + 1 && src[i + 1] !== " " && src[j - 1] !== " ") { flush(); out.push({ t: "em", c: parseInline(src.slice(i + 1, j)) }); i = j + 1; continue; }
    }
    if (ch === "[") {
      const m = /^\[([^\]]+)\]\(([^)\s]+)\)/.exec(src.slice(i));
      if (m) {
        const href = safeHref(m[2]);
        flush();
        if (href) out.push({ t: "link", href, c: parseInline(m[1]) }); else out.push({ t: "text", v: m[1] });
        i += m[0].length; continue;
      }
    }
    buf += ch; i++;
  }
  flush();
  return out;
}

export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  const para: string[] = [];
  const flushPara = () => { if (para.length) { out.push({ t: "p", c: parseInline(para.join("\n")) }); para.length = 0; } };
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^```\s*([\w+-]*)\s*$/.exec(line);
    if (fence) {
      flushPara();
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) body.push(lines[i++]);
      i++;                                   // closing fence (an unterminated block runs to the end, like most renderers)
      out.push({ t: "code", lang: fence[1], v: body.join("\n") });
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) { flushPara(); out.push({ t: "h", level: h[1].length as 1 | 2 | 3 | 4, c: parseInline(h[2].trim()) }); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flushPara(); out.push({ t: "hr" }); i++; continue; }
    if (/^\s*[-*+]\s+/.test(line)) {
      flushPara();
      const items: Inline[][] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) items.push(parseInline(lines[i++].replace(/^\s*[-*+]\s+/, "")));
      out.push({ t: "ul", items }); continue;
    }
    const ol = /^\s*(\d+)[.)]\s+/.exec(line);
    if (ol) {
      flushPara();
      const items: Inline[][] = [];
      const start = Number(ol[1]);
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(parseInline(lines[i++].replace(/^\s*\d+[.)]\s+/, "")));
      out.push({ t: "ol", items, start }); continue;
    }
    if (/^>\s?/.test(line)) {
      flushPara();
      const q: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) q.push(lines[i++].replace(/^>\s?/, ""));
      out.push({ t: "quote", c: parseInline(q.join("\n")) }); continue;
    }
    if (line.trim() === "") { flushPara(); i++; continue; }
    para.push(line); i++;
  }
  flushPara();
  return out;
}
