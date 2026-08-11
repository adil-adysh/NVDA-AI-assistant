#!/usr/bin/env python3
"""
Harrier Embedding Model — Comprehensive Validation Suite.

Run with::

    python -m tests.harrier.run_validation

This runs ALL validation suites and produces:
- ``harrier_validation_results.json`` — machine-readable results
- ``harrier_validation_report.md`` — human-readable report

Exit code 0 = all critical tests pass
Exit code 1 = one or more critical failures
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from .runners import HFHarrierRunner, RustHarrierRunner
from .suites import run_all_suites
from .reporter import generate_json_report, generate_markdown_report
from .suites import RESULT_FAIL


def main() -> int:
    """Run all validation suites and generate reports. Returns exit code."""
    print("=" * 72)
    print("  Harrier Embedding Model — Validation Suite")
    print(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)
    print()

    # Initialize runners
    print("[1/4] Initializing runners...")
    hf = HFHarrierRunner()
    rust = RustHarrierRunner()

    print("      Warming up HF reference model...")
    hf.warm_up()
    print("      Warming up Rust/Candle model...")
    rust.warm_up()
    dims = rust.dimensions()
    max_tok = rust.max_tokens()
    print(f"      Rust model: {dims} dims, {max_tok} max tokens")
    print()

    # Run suites
    print("[2/4] Running validation suites...")
    suites = run_all_suites(hf, rust)
    print()

    # Print summary
    print("[3/4] Results:")
    print()
    for s in suites:
        icon = "PASS" if s.status == "PASS" else ("FAIL" if s.status == "FAIL" else s.status)
        print(f"  {s.name:40s}  {icon:6s}  "
              f"({s.passed} pass, {s.failed} fail, {s.warnings} warn)"
              f"  [{s.timing.elapsed_seconds:.1f}s]" if s.timing else "")
    print()

    # Generate reports
    print("[4/4] Generating reports...")
    json_path = generate_json_report(suites)
    md_path = generate_markdown_report(suites)
    print(f"      JSON:    {json_path}")
    print(f"      Markdown: {md_path}")
    print()

    # Determine exit code
    critical_failures = sum(
        1 for s in suites
        if s.status == RESULT_FAIL
        and s.name not in (
            "11_performance", "12_failure_tests", "14_threshold_calibration"
        )
    )
    if critical_failures > 0:
        print(f"  ❌ {critical_failures} critical suite(s) FAILED.")
        print()
        return 1

    total = sum(s.total_tests for s in suites)
    passed = sum(s.passed for s in suites)
    _failed = sum(s.failed for s in suites)
    _warnings = sum(s.warnings for s in suites)
    print(f"  ✅ All critical suites passed! ({passed}/{total} tests passed)")
    if _warnings > 0:
        print(f"  \u26a0\ufe0f  {_warnings} warning(s) — see report for details.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
