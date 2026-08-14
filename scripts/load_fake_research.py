#!/usr/bin/env python3
"""Run N free-path researches and write an honest load artifact (p50/p95).

Not a capacity plan: single process, fixture retriever, cold-start noted.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from pathlib import Path

from agentic_rag.agent import run_research
from agentic_rag.tools import FakeRetrievalBackend, RetrieveTool

QUESTIONS = [
    "How does reciprocal rank fusion score a document?",
    "What does the pipeline do when the reranker is unavailable?",
    "Why is the count of dropped citation markers worth recording?",
    "How does a chunk keep a stable identifier across a re-ingest?",
    "Who won the 2099 Antarctic chess championship?",
    "What were the quarterly revenues in Patagonia?",
    "How does the Reykjavik trampoline audit affect chunking?",
    "What is the hard step budget every agent loop carries?",
]


def percentile(sorted_values: list[float], p: float) -> float:
    """Return the linear-interpolated percentile ``p`` of sorted latencies."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def main() -> int:
    """CLI entry: run N researches and write the load JSON artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/assets/load.json"),
    )
    args = parser.parse_args()
    tool = RetrieveTool(FakeRetrievalBackend())
    # Cold start (import + first run)
    cold_t0 = time.perf_counter()
    run_research(QUESTIONS[0], tool=tool, max_steps=4)
    cold_ms = (time.perf_counter() - cold_t0) * 1000

    latencies: list[float] = []
    statuses: dict[str, int] = {}
    for i in range(args.n):
        q = QUESTIONS[i % len(QUESTIONS)]
        t0 = time.perf_counter()
        state = run_research(q, tool=tool, max_steps=4)
        latencies.append((time.perf_counter() - t0) * 1000)
        statuses[state.status.value] = statuses.get(state.status.value, 0) + 1

    ordered = sorted(latencies)
    artifact = {
        "label": "honest single-process free-path load — not production capacity",
        "n": args.n,
        "retriever": "fake",
        "billed": False,
        "hardware": {
            "machine": platform.machine(),
            "processor": platform.processor(),
            "system": platform.system(),
            "python": platform.python_version(),
        },
        "cold_start_ms": round(cold_ms, 3),
        "latency_ms": {
            "p50": round(percentile(ordered, 50), 3),
            "p95": round(percentile(ordered, 95), 3),
            "mean": round(statistics.fmean(latencies), 3),
            "min": round(min(latencies), 3),
            "max": round(max(latencies), 3),
        },
        "status_counts": statuses,
        "notes": [
            "Fixture retriever only; no HTTP P1; no OpenAI.",
            "Single process on the machine that ran the script.",
            "Cold-start is first run after process start, included separately.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
