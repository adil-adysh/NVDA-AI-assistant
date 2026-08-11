"""
Report generation for Harrier validation results.

Produces:
- ``harrier_validation_results.json`` — machine-readable JSON
- ``harrier_validation_report.md`` — human-readable Markdown report
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .suites import SuiteResult, RESULT_PASS, RESULT_FAIL, RESULT_WARNING


# ── JSON Reporter ────────────────────────────────────────────────────────────


def _suite_to_json(suite: SuiteResult) -> dict[str, Any]:
    """Convert a SuiteResult to JSON-serializable dict."""
    return {
        "name": suite.name,
        "category": suite.category,
        "status": suite.status,
        "total_tests": suite.total_tests,
        "passed": suite.passed,
        "failed": suite.failed,
        "warnings": suite.warnings,
        "distribution": suite.distribution,
        "timing": {
            "name": suite.timing.name,
            "seconds": suite.timing.elapsed_seconds,
        } if suite.timing else None,
        "note": suite.note,
        "results": [
            {
                "test_id": r.test_id,
                "category": r.category,
                "status": r.status,
                "metrics": r.metrics,
                "hf_result": r.hf_result,
                "rust_result": r.rust_result,
                "difference": r.difference,
                "note": r.note,
            }
            for r in suite.results
        ],
    }


def generate_json_report(
    suites: list[SuiteResult],
    output_path: str = "harrier_validation_results.json",
) -> str:
    """Generate JSON report and write to file. Returns the path."""
    report = {
        "title": "Harrier Embedding Model Validation Report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "microsoft/harrier-oss-v1-270m",
        "implementation": "Rust/Candle (embedding_engine)",
        "summary": _compute_summary(suites),
        "suites": [_suite_to_json(s) for s in suites],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    return output_path


# ── Markdown Reporter ────────────────────────────────────────────────────────


def _compute_summary(suites: list[SuiteResult]) -> dict[str, Any]:
    """Compute overall summary across suites."""
    total = sum(s.total_tests for s in suites)
    passed = sum(s.passed for s in suites)
    failed = sum(s.failed for s in suites)
    warnings = sum(s.warnings for s in suites)
    suite_statuses = {}
    for s in suites:
        suite_statuses[s.name] = s.status

    return {
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "suite_statuses": suite_statuses,
    }


def _status_icon(status: str) -> str:
    if status == RESULT_PASS:
        return "✅"
    elif status == RESULT_FAIL:
        return "❌"
    elif status == RESULT_WARNING:
        return "⚠️"
    else:
        return "ℹ️"


def _distribution_table(dist: dict[str, Any]) -> str:
    """Render a distribution dict as a markdown table row."""
    if not dist:
        return "_No data_"
    keys = ["count", "mean", "median", "std", "min", "max", "p1", "p5", "p95", "p99"]
    vals = []
    for k in keys:
        if k in dist:
            v = dist[k]
            if isinstance(v, float):
                vals.append(f"{v:.6f}")
            else:
                vals.append(str(v))
    return " | ".join(vals)


def _distribution_header() -> str:
    return "count | mean | median | std | min | max | p1 | p5 | p95 | p99"


def generate_markdown_report(
    suites: list[SuiteResult],
    output_path: str = "harrier_validation_report.md",
) -> str:
    """Generate Markdown report and write to file. Returns the path."""
    summary = _compute_summary(suites)

    lines: list[str] = []

    # Title
    lines.append("# Harrier Embedding Model Validation Report")
    lines.append("")
    lines.append("**Generated:** " + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
    lines.append("")
    lines.append("**Model:** `microsoft/harrier-oss-v1-270m`")
    lines.append("**Implementation:** Rust/Candle (`embedding_engine`)")
    lines.append("")

    # Executive Summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total tests | {summary['total_tests']} |")
    lines.append(f"| Passed | {summary['passed']} |")
    lines.append(f"| Failed | {summary['failed']} |")
    lines.append(f"| Warnings | {summary['warnings']} |")
    lines.append("")

    # Suite status overview
    lines.append("### Suite Status Overview")
    lines.append("")
    lines.append("| Suite | Status | Tests | Passed | Failed | Warnings | Time (s) |")
    lines.append("|-------|--------|-------|--------|--------|----------|----------|")
    for s in suites:
        icon = _status_icon(s.status)
        timing = f"{s.timing.elapsed_seconds:.1f}" if s.timing else "—"
        lines.append(
            f"| {icon} {s.name} | {s.status} | {s.total_tests} | "
            f"{s.passed} | {s.failed} | {s.warnings} | {timing} |"
        )
    lines.append("")

    # Per-suite details
    for s in suites:
        lines.append(f"## {s.name}")
        lines.append("")
        if s.note:
            lines.append(f"> {s.note}")
            lines.append("")

        # Distribution data
        if s.distribution:
            lines.append("### Distribution")
            lines.append("")
            if isinstance(s.distribution, dict):
                # Check if it's relational distributions
                first_val = next(iter(s.distribution.values()), None)
                if isinstance(first_val, dict) and "mean" in first_val:
                    lines.append("| Category | " + _distribution_header() + " |")
                    lines.append("|----------|" + "---|" * 10)
                    for rel, dist in s.distribution.items():
                        lines.append(f"| {rel} | {_distribution_table(dist)} |")
                    lines.append("")
                else:
                    lines.append("| Key | Value |")
                    lines.append("|-----|-------|")
                    for k, v in s.distribution.items():
                        if isinstance(v, float):
                            lines.append(f"| {k} | {v:.6f} |")
                        else:
                            lines.append(f"| {k} | {v} |")
                    lines.append("")

        # Failed/warning results
        failures = [r for r in s.results if r.status == RESULT_FAIL]
        if failures:
            lines.append("### ❌ Failures")
            lines.append("")
            lines.append("| Test ID | Metrics | Note |")
            lines.append("|---------|---------|------|")
            for r in failures:
                metric_str = json.dumps(r.metrics, default=str)[:120]
                lines.append(f"| {r.test_id} | {metric_str} | {r.note} |")
            lines.append("")

        warnings_list = [r for r in s.results if r.status == RESULT_WARNING and s.name != "12_failure_tests"]
        if warnings_list:
            lines.append("### ⚠️ Warnings")
            lines.append("")
            lines.append("| Test ID | Metrics | Note |")
            lines.append("|---------|---------|------|")
            for r in warnings_list[:20]:  # Limit to 20
                metric_str = json.dumps(r.metrics, default=str)[:120]
                lines.append(f"| {r.test_id} | {metric_str} | {r.note} |")
            if len(warnings_list) > 20:
                lines.append(f"| ... | _({len(warnings_list) - 20} more)_ | |")
            lines.append("")

    # Final acceptance checklist
    lines.append("## Acceptance Checklist")
    lines.append("")
    suite_map = {s.name: s.status for s in suites}

    checklist_items = [
        ("01_numerical_parity", "HF/Rust numerical parity >= 0.9999"),
        ("10_determinism", "Deterministic output (no NaN/Inf)"),
        ("07_long_context", "Long-context tests pass (including 513-token boundary)"),
        ("05_multilingual", "Multilingual tests pass"),
        ("08_query_document", "Query/document behavior is correct"),
        ("13_ranking_consistency", "Retrieval ranking consistent with HF"),
        ("04_hard_negatives", "Hard negatives handled reasonably"),
        ("06_nvda_realworld", "NVDA-like noisy text works reasonably"),
        ("15_regression", "All regression tests pass"),
        ("03_retrieval", "Retrieval accuracy acceptable"),
        ("09_edge_cases", "Edge cases: no NaN/Inf, correct dim, stable norm"),
    ]

    for name, desc in checklist_items:
        status = suite_map.get(name, "NOT_RUN")
        icon = _status_icon(status)
        lines.append(f"- [{icon}] **{desc}** _(status: {status})_")
    lines.append("")

    # Recommendations
    lines.append("## Recommendations")
    lines.append("")

    if summary["failed"] == 0:
        lines.append("All critical tests passed. The Harrier implementation is:"
                      if summary["warnings"] == 0 else
                      "Most tests passed with some warnings. The Harrier implementation is likely:")
        lines.append("")
        lines.append("- ✅ Mathematically faithful to the reference model")
        lines.append("- ✅ Useful for real-world semantic retrieval")
        lines.append("- ✅ Ready for production use in NVDA AI Assistant")
        if summary["warnings"] > 0:
            lines.append("- \u26a0\ufe0f {summary['warnings']} warnings to investigate")
    else:
        lines.append(f"{summary['failed']} test(s) failed. Review failures above before production use.")
        lines.append("")
        lines.append("Do NOT assume numerical parity is sufficient for correctness.")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by Harrier Validation Suite v1.0.0*")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path
