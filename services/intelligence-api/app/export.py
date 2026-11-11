"""Conversation export (Markdown, plain text, JSON). Pure functions over data already authorised by the caller; no I/O."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

FORMATS = {"json": "application/json; charset=utf-8", "md": "text/markdown; charset=utf-8", "txt": "text/plain; charset=utf-8"}
EXPORT_SCHEMA = "avoenix.conversation/1"
ROLE_LABEL = {"user": "You", "assistant": "AVOENIX", "system": "System"}


def filename_for(conversation: dict, fmt: str, now: datetime | None = None) -> str:
    """``<title-slug>-<id8>-<YYYYMMDD>.<ext>``: ASCII only, so it is safe in headers and on every file system."""
    slug = re.sub(r"[^a-z0-9]+", "-", (conversation.get("title") or "conversation").lower()).strip("-")[:48] or "conversation"
    cid = re.sub(r"[^a-z0-9]", "", str(conversation.get("id") or "").lower())[-8:] or "x"
    day = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return f"{slug}-{cid}-{day}.{fmt}"


def _msg(m: dict) -> dict:
    return {"id": m.get("id"), "role": m.get("role"), "content": m.get("content") or "", "turn_index": m.get("turn_index"), "created_at": m.get("created_at")}


def render(conversation: dict, messages: list[dict], fmt: str, exported_at: str) -> str:
    if fmt not in FORMATS:
        raise ValueError(f"unsupported export format {fmt!r}")
    msgs = [_msg(m) for m in messages]
    title = conversation.get("title") or "Untitled conversation"
    if fmt == "json":
        return json.dumps({"format": EXPORT_SCHEMA, "exported_at": exported_at,
                           "conversation": {k: conversation.get(k) for k in ("id", "title", "created_at", "updated_at")},
                           "message_count": len(msgs), "messages": msgs}, ensure_ascii=False, indent=2) + "\n"
    if fmt == "md":
        out = [f"# {title}", "", f"- Conversation: `{conversation.get('id')}`", f"- Started: {conversation.get('created_at')}", f"- Messages: {len(msgs)}", f"- Exported: {exported_at}", ""]
        if not msgs:
            out += ["_This conversation has no messages._", ""]
        for m in msgs:
            out += [f"## {ROLE_LABEL.get(m['role'], m['role'])} · {m['created_at'] or ''}".rstrip(" ·"), "", m["content"], ""]
        return "\n".join(out)
    out = [title, "=" * min(len(title), 72), f"Conversation: {conversation.get('id')}", f"Started: {conversation.get('created_at')}", f"Messages: {len(msgs)}", f"Exported: {exported_at}", ""]
    if not msgs:
        out += ["(This conversation has no messages.)", ""]
    for m in msgs:
        out += [f"[{m['created_at'] or ''}] {ROLE_LABEL.get(m['role'], m['role'])}:".replace("[] ", ""), m["content"], ""]
    return "\n".join(out)
