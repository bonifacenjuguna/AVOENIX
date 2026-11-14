#!/usr/bin/env python
"""Print the meaning-layer inspection for a scripted conversation (local developer tool; runs an isolated in-memory engine, touches no real data).

    python scripts/trace_turn.py "I bought a new laptop yesterday." "It was expensive." "Who makes it?"
    python scripts/trace_turn.py --json "Where do I live?"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from intelligence.app import Avoenix, AvoenixConfig  # noqa: E402
from intelligence.core.types import Scope  # noqa: E402
from intelligence.storage import MemoryBackend  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("turns", nargs="+", help="user messages, in order")
    ap.add_argument("--json", action="store_true", help="emit the full inspection records as JSON")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    app = Avoenix(MemoryBackend(), AvoenixConfig(diagnostics=True, deterministic_seed=a.seed))
    sc, cid, records = Scope("trace", "local"), None, []
    for t in a.turns:
        r = app.process_turn(sc, t, cid)
        cid = r.conversation_id
        ins = (r.response_meta.get("meaning") or {}).get("inspection")
        records.append({"input": t, "response": r.response, "status": r.status, "inspection": ins})
        if not a.json:
            print(f"\nUSER      {t}\nAVOENIX   {r.response}   [{r.status}]")
            if not ins:
                print("  (the meaning layer did not handle this turn; the legacy pipeline answered)")
                continue
            for k, v in ins.items():
                print(f"  {k}: {json.dumps(v, default=str, ensure_ascii=False)[:400]}")
    if a.json:
        print(json.dumps(records, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
