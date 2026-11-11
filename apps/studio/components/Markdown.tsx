import { Fragment } from "react";
import { Block, Inline, parseBlocks } from "@/lib/markdown";

function Inl({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((n, i) => {
        switch (n.t) {
          case "text": return <Fragment key={i}>{n.v}</Fragment>;
          case "code": return <code key={i}>{n.v}</code>;
          case "strong": return <strong key={i}><Inl nodes={n.c} /></strong>;
          case "em": return <em key={i}><Inl nodes={n.c} /></em>;
          case "link": return <a key={i} href={n.href} target="_blank" rel="noopener noreferrer nofollow"><Inl nodes={n.c} /></a>;
        }
      })}
    </>
  );
}

function Blk({ b }: { b: Block }) {
  switch (b.t) {
    case "p": return <p className="whitespace-pre-wrap break-words"><Inl nodes={b.c} /></p>;
    case "h": { const H = (`h${b.level}`) as "h1" | "h2" | "h3" | "h4"; return <H><Inl nodes={b.c} /></H>; }
    case "ul": return <ul>{b.items.map((it, i) => <li key={i}><Inl nodes={it} /></li>)}</ul>;
    case "ol": return <ol start={b.start}>{b.items.map((it, i) => <li key={i}><Inl nodes={it} /></li>)}</ol>;
    case "code": return <pre tabIndex={0} aria-label={b.lang ? `${b.lang} code` : "code"}><code>{b.v}</code></pre>;
    case "quote": return <blockquote className="whitespace-pre-wrap"><Inl nodes={b.c} /></blockquote>;
    case "hr": return <hr />;
  }
}

/** Renders a Markdown subset with React elements only (no innerHTML). */
export function Markdown({ text }: { text: string }) {
  return <div className="md break-words">{parseBlocks(text).map((b, i) => <Blk key={i} b={b} />)}</div>;
}
