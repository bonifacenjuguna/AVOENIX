#!/usr/bin/env python
"""Measure per-turn latency on the in-memory backend (real orchestrator, no mocks). Reports what was measured; results are machine-dependent and NOT a capacity claim.

    python scripts/measure_performance.py [--turns 200]
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intelligence.app import Avoenix, AvoenixConfig  # noqa: E402
from intelligence.core.types import Scope  # noqa: E402
from intelligence.storage import MemoryBackend  # noqa: E402

MIX = {"question_established": "What is the capital of Kenya?", "claim_contradicting": "The capital of Kenya is Mombasa.", "claim_unknown": "The capital of Atlantis is Poseidonis.",
       "ordering": "John is older than Peter. Peter is older than David. Who is the youngest?", "personal": "My name is Savah."}


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 2)


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--turns", type=int, default=200)
    n = ap.parse_args().turns
    app = Avoenix(MemoryBackend(), AvoenixConfig())
    out = {}
    for name, text in MIX.items():
        lat = []
        for i in range(n):
            scope = Scope("perf", f"u_{name}_{i % 20}")          # 20 users per kind, so per-user claim sets grow realistically
            t0 = time.perf_counter(); app.process_turn(scope, text, None); lat.append((time.perf_counter() - t0) * 1000)
        out[name] = {"n": n, "p50_ms": pct(lat, .5), "p95_ms": pct(lat, .95), "max_ms": round(max(lat), 2), "mean_ms": round(statistics.mean(lat), 2)}
    print(json.dumps({"backend": "memory", "python": platform.python_version(), "platform": platform.platform(), "results": out}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
