#!/usr/bin/env python
"""Run the evaluation dataset against the real orchestrator (in-memory backend) and print/write a JSON report.

    python scripts/run_evaluation.py [--dataset evaluation/datasets/core_v0.json] [--out evaluation/results/latest.json] [--split holdout]

Every case runs in a fresh user scope. Failures are reported, never adjusted. Targets are development goals only.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from intelligence.app import Avoenix, AvoenixConfig  # noqa: E402
from intelligence.core.types import Scope  # noqa: E402
from intelligence.storage import MemoryBackend  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "evaluation/datasets/core_v0.json"))
    ap.add_argument("--out", default=str(ROOT / "evaluation/results/latest.json"))
    ap.add_argument("--split", default=None, help="only run this split (dev|holdout)")
    ap.add_argument("--no-meaning", action="store_true", help="disable the meaning layer (reproduces the v0.0.1 pipeline)")
    args = ap.parse_args()
    data = json.loads(Path(args.dataset).read_text())
    cases = [c for c in data["cases"] if not args.split or c.get("split") == args.split]
    app = Avoenix(MemoryBackend(), AvoenixConfig(meaning_enabled=not args.no_meaning))
    counter = {"n": 0}

    def claim_state(scope: Scope) -> dict:
        cl = app.knowledge.claims(scope)
        return {"claims": [{"object": (c.object or {}).get("label") if isinstance(c.object, dict) else str(c.object), "verification": c.verification, "provenance": c.provenance,
                            "memory_linked": bool(c.memory_id)} for c in cl],
                "open_conflicts": len(app.knowledge.conflicts(scope, status="open")),
                "revisions": len(app.backend.select("knowledge_revisions", {"project_id": scope.project_id, "user_id": scope.user_id}))}

    def respond(case: dict) -> list[dict]:
        counter["n"] += 1
        scope = Scope("eval", f"eval_user_{counter['n']}")
        cid, turns = None, []
        for text in case["turns"]:
            r = app.process_turn(scope, text, cid)
            cid = r.conversation_id
            turns.append({"response": r.response, "understanding": r.understanding, "reasoning_status": (r.response_meta or {}).get("reasoning_status"),
                          "emoji": (r.response_meta or {}).get("emoji"), "confidence": (r.confidence or {}).get("overall"),
                          **claim_state(scope)})
        return turns

    report = app.evaluation.run_suite(cases, respond, label=Path(args.dataset).stem, environment={"python": platform.python_version(), "backend": "memory", "platform": platform.platform()})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    s = report["summary"]
    print(f"overall: {s['overall']['passed']}/{s['overall']['total']}  splits: {s['by_split']}")
    for k, v in s["metrics"].items():
        print(f"  {k}: {v['passed']}/{v['total']} acc={v['accuracy']} target={v['target']} -> {v['status']}")
    for c, v in s["by_category"].items():
        print(f"  [{c}] {v['passed']}/{v['total']}")
    for f in report["failures"]:
        print("FAIL", f["id"], f["reasons"])
    print(f"report written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
