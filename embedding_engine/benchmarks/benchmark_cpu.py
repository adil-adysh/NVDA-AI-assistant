"""
CPU embedding benchmark — separate from correctness/integration tests.

Measures:
  - First-embed latency (model load / JIT warmup)
  - Warm-embed latency (post-warmup throughput)
  - Batch throughput at various sizes
  - Unicode text latency (no regression)

Run with:
    python benchmarks/benchmark_cpu.py
"""

from __future__ import annotations

import math
import statistics
import sys
import time
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import embedding_engine

WARMUP_RUNS = 3
TIMED_RUNS = 10
BATCH_SIZES = [1, 2, 4, 8, 16]

SHORT_TEXT = "The quick brown fox jumps over the lazy dog."
UNICODE_TEXT = "नमस्ते दुनिया — embedding multilingual text."
LONG_TEXT = "word " * 200  # ~200 tokens


def _configure_console() -> None:
    """Keep benchmark output readable on Windows cp1252 consoles."""
    stream = getattr(sys, "stdout", None)
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)))


def bench(name: str, fn, runs: int = TIMED_RUNS) -> list[float]:
    """Run *fn* *runs* times and return list of latencies in seconds."""
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return times


def report(name: str, times: list[float]) -> None:
    mean = statistics.mean(times) * 1000
    stdev = statistics.stdev(times) * 1000 if len(times) > 1 else 0.0
    print(f"  {name:<30} {mean:>7.1f} ms  (±{stdev:.1f} ms, n={len(times)})")


def main() -> None:
    _configure_console()
    print("=" * 60)
    print("Embedding Engine CPU Benchmark")
    print("=" * 60)

    engine = embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")

    # Warm up — first call triggers model download/load
    print("\n--- Warmup ---")
    t0 = time.perf_counter()
    _ = engine.embed(SHORT_TEXT)
    first_latency = time.perf_counter() - t0
    print(f"  First embed (incl. load): {first_latency:.1f}s")
    for _ in range(WARMUP_RUNS - 1):
        _ = engine.embed(SHORT_TEXT)

    # Single-text latency
    print("\n--- Single-Text Latency ---")
    report("short (English)", bench("short", lambda: engine.embed(SHORT_TEXT)))
    report("unicode (Hindi)", bench("unicode", lambda: engine.embed(UNICODE_TEXT)))
    report("long (~200 tokens)", bench("long", lambda: engine.embed(LONG_TEXT)))

    # Batch throughput
    print("\n--- Batch Throughput ---")
    for size in BATCH_SIZES:
        texts = [f"This is benchmark sentence number {i}." for i in range(size)]

        def batch_fn():
            return engine.embed_batch(texts)

        times = bench(f"batch_{size}", batch_fn)
        mean_total = statistics.mean(times) * 1000
        mean_per_text = mean_total / size
        print(
            f"  batch {size:>2}: {mean_total:>7.1f} ms total  "
            f"({mean_per_text:.2f} ms/text, n={len(times)})"
        )

    # Quality sanity (not a threshold, just informational)
    print("\n--- Quality Sanity (informational) ---")
    sim_a = engine.embed("The quick brown fox jumps over the lazy dog.")
    sim_b = engine.embed("A fast brown fox leaped over a sleepy canine.")
    unr = engine.embed("Machine learning models require large amounts of training data.")
    print(f"  Similar pair cosine:    {_cosine(sim_a, sim_b):.4f}")
    print(f"  Unrelated pair cosine:  {_cosine(sim_a, unr):.4f}")

    print("\n" + "=" * 60)
    print("Benchmark complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
