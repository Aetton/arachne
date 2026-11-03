#!/usr/bin/env python3
"""Compare runview.build() memory/time on a large synthetic journal.

Usage: PYTHONPATH=api python scripts/benchmark_runview.py --lines 100000
This profiles ONLY run-view grouping; it does not measure run_engine,
JSON deserialization, database I/O, or browser DOM.
"""
from __future__ import annotations
import argparse
import gc
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import runview


def bench(records: list[dict], include_lines: bool) -> tuple[float, int, int]:
    gc.collect()
    tracemalloc.start()
    start = time.perf_counter()
    steps = runview.build(records, "success", include_lines=include_lines)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    groups = sum(len(x["tasks"]) for x in steps)
    return elapsed, peak, groups


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines", type=int, default=100000)
    args = parser.parse_args()
    if args.lines < 1:
        parser.error("--lines must be >= 1")
    records = [
        {"step_id": "build", "stream": "system", "text": "━━━ step 'build' via forgejo ━━━"},
        {"step_id": "build", "stream": "stdout", "text": "TASK [Build]"},
    ]
    records.extend(
        {"step_id": "build", "stream": "stdout",
         "text": "test-log-line-" + str(i) + " x" * 20}
        for i in range(args.lines)
    )
    full_time, full_peak, groups = bench(records, True)
    compact_time, compact_peak, _ = bench(records, False)
    print(f"Input records: {len(records):,}, task groups: {groups:,}")
    print(f"Full:    {full_time:.3f}s, tracked peak {full_peak/1048576:.2f} MiB")
    print(f"Compact: {compact_time:.3f}s, tracked peak {compact_peak/1048576:.2f} MiB")
    print("Note: this excludes input records, DB queries, JSON decode and client rendering.")


if __name__ == "__main__":
    main()
