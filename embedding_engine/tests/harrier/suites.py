"""
Test suites for Harrier embedding model validation.

Each suite takes HF and Rust runners, runs tests, and returns structured results.
Suites are independent — the runner orchestrates them and aggregates results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .datasets import (
    NUMERICAL_PARITY_SHORT_QUERIES,
    NUMERICAL_PARITY_DOCUMENTS,
    NUMERICAL_PARITY_MULTILINGUAL,
    NUMERICAL_PARITY_LONG,
    SEMANTIC_POSITIVE_PAIRS,
    RETRIEVAL_TECH_DOCS,
    HARD_NEGATIVE_QUERIES,
    MULTILINGUAL_PAIRS,
    MULTILINGUAL_RETRIEVAL,
    NVDA_REALWORLD_TEXTS,
    LONG_CONTEXT_TEXTS,
    LONG_CONTEXT_POSITION_TESTS,
    EDGE_CASES,
    REGRESSION_TESTS,
)
from .metrics import (
    cosine,
    compare_all_embeddings,
    compare_embeddings,
    compute_distribution,
    retrieval_metrics,
    ranking_overlap,
    top1_agreement,
    kendall_tau,
    is_deterministic,
    vector_norm,
)
from .runners import (
    HFHarrierRunner,
    RustHarrierRunner,
    TimerResult,
    time_it,
    HARRIER_DIM,
)

# ── Result types ──────────────────────────────────────────────────────────────

RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"
RESULT_WARNING = "WARNING"
RESULT_NA = "NOT_APPLICABLE"


@dataclass
class TestResult:
    """Result of a single test case."""

    test_id: str
    category: str
    status: str  # PASS, FAIL, WARNING, NOT_APPLICABLE
    metrics: dict[str, Any] = field(default_factory=dict)
    hf_result: Any = None
    rust_result: Any = None
    difference: Any = None
    note: str = ""


@dataclass
class SuiteResult:
    """Aggregate result for an entire test suite."""

    name: str
    category: str
    status: str  # PASS, FAIL, WARNING
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    results: list[TestResult] = field(default_factory=list)
    distribution: dict[str, Any] = field(default_factory=dict)
    timing: TimerResult | None = None
    note: str = ""


# ── 01 Numerical Parity ─────────────────────────────────────────────────────


def run_numerical_parity(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Test HF vs Rust numerical parity across diverse inputs."""
    results: list[TestResult] = []
    hf_embs: list[list[float]] = []
    rust_embs: list[list[float]] = []

    datasets = {
        "short_queries": NUMERICAL_PARITY_SHORT_QUERIES,
        "documents": NUMERICAL_PARITY_DOCUMENTS,
        "multilingual": NUMERICAL_PARITY_MULTILINGUAL,
        "long": NUMERICAL_PARITY_LONG,
    }

    for cat_name, items in datasets.items():
        for item in items:
            tid = item["id"]
            text = item["text"]
            try:
                # HF: run as query (worst case for parity)
                hf_vec = hf.embed_query(text)
                rust_vec = rust.embed_query(text)
                comp = compare_embeddings(hf_vec, rust_vec)
                hf_embs.append(hf_vec)
                rust_embs.append(rust_vec)

                status = RESULT_PASS if comp["cosine"] >= 0.9999 else RESULT_FAIL
                results.append(TestResult(
                    test_id=tid, category="numerical_parity",
                    status=status, metrics=comp,
                    note=f"cos={comp['cosine']:.6f} max_abs={comp['max_abs_diff']:.2e}",
                ))
            except Exception as exc:
                results.append(TestResult(
                    test_id=tid, category="numerical_parity",
                    status=RESULT_FAIL, metrics={"error": str(exc)},
                ))

    agg = compare_all_embeddings(hf_embs, rust_embs)
    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)

    return SuiteResult(
        name="01_numerical_parity",
        category="numerical_parity",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
        distribution=agg["cosine_distribution"],
    )


# ── 02 Semantic Similarity ─────────────────────────────────────────────────


def run_semantic_similarity(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Test semantic similarity across positive, hard-negative, and unrelated pairs."""
    results: list[TestResult] = []
    all_cosines: dict[str, list[float]] = {
        "exact_match": [], "paraphrase": [], "related": [],
        "hard_negative": [], "unrelated": [],
    }

    for case in SEMANTIC_POSITIVE_PAIRS:
        tid = case.id
        try:
            # Use document mode for both (no instruction)
            hf_a = hf.embed_document(case.text_a)
            hf_b = hf.embed_document(case.text_b)
            rust_a = rust.embed_document(case.text_a)
            rust_b = rust.embed_document(case.text_b)

            hf_cos = cosine(hf_a, hf_b)
            rust_cos = cosine(rust_a, rust_b)

            all_cosines.setdefault(case.expected_relationship, []).append(rust_cos)

            # For semantic tests, we don't compare HF vs Rust cosines directly.
            # We check that the relationship is reasonable for Rust.
            rel = case.expected_relationship
            is_reasonable = True
            if rel == "exact_match":
                is_reasonable = rust_cos >= 0.95
            elif rel == "paraphrase":
                is_reasonable = rust_cos >= 0.7
            elif rel in ("related", "hard_negative"):
                # Hard negatives should score lower than paraphrases
                # but we don't enforce a specific threshold
                is_reasonable = rust_cos >= 0.0
            elif rel == "unrelated":
                is_reasonable = rust_cos < 0.8  # should be distinguishable

            status = RESULT_PASS if is_reasonable else RESULT_WARNING
            results.append(TestResult(
                test_id=tid,
                category="semantic_similarity",
                status=status,
                metrics={
                    "hf_cosine": hf_cos,
                    "rust_cosine": rust_cos,
                    "expected_relationship": rel,
                },
                hf_result=hf_cos,
                rust_result=rust_cos,
                difference=abs(hf_cos - rust_cos),
                note=f"rel={rel} hf_cos={hf_cos:.4f} rust_cos={rust_cos:.4f}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="semantic_similarity",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)
    warnings = sum(1 for r in results if r.status == RESULT_WARNING)

    dist = {
        rel: compute_distribution(vals)
        for rel, vals in all_cosines.items()
    }

    return SuiteResult(
        name="02_semantic_similarity",
        category="semantic_similarity",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        warnings=warnings,
        results=results,
        distribution=dist,
    )


# ── 03 Retrieval ────────────────────────────────────────────────────────────


def run_retrieval(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Test retrieval accuracy on a document collection."""
    results: list[TestResult] = []
    dataset = RETRIEVAL_TECH_DOCS

    # Embed all documents once
    hf_docs = hf.embed_batch(dataset.documents, is_query=False)
    rust_docs = rust.embed_batch(dataset.documents, is_query=False)

    for qi, qdata in enumerate(dataset.queries):
        query_text = qdata["query"]
        relevant = set(qdata["relevant"])
        tid = f"ret_{qi:03d}"

        try:
            hf_query = hf.embed_query(query_text)
            rust_query = rust.embed_query(query_text)

            hf_met = retrieval_metrics(hf_query, hf_docs, relevant, k_values=[1, 3, 5, 10])
            rust_met = retrieval_metrics(rust_query, rust_docs, relevant, k_values=[1, 3, 5, 10])

            # Check ranking agreement
            top1_agree = top1_agreement(
                hf_met["ranked_indices"], rust_met["ranked_indices"]
            )
            overlap_data = {}
            for k in [1, 3, 5, 10]:
                overlap_data.update(
                    ranking_overlap(hf_met["ranked_indices"], rust_met["ranked_indices"], k)
                )

            # A query passes if at least recall@3 > 0
            status = RESULT_PASS if rust_met["recall@3"] > 0 else RESULT_FAIL

            results.append(TestResult(
                test_id=tid, category="retrieval", status=status,
                metrics={
                    "hf": hf_met, "rust": rust_met,
                    "top1_agreement": top1_agree,
                    **overlap_data,
                },
                note=f"rust_recall@3={rust_met['recall@3']:.2f} hf_recall@3={hf_met['recall@3']:.2f}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="retrieval",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)

    return SuiteResult(
        name="03_retrieval",
        category="retrieval",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
    )


# ── 04 Hard Negatives ───────────────────────────────────────────────────────


def run_hard_negatives(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Test hard-negative retrieval where lexical overlap is deceptive."""
    results: list[TestResult] = []

    for case in HARD_NEGATIVE_QUERIES:
        tid = case.id
        try:
            rust_query = rust.embed_query(case.query)
            rust_docs = rust.embed_batch(case.documents, is_query=False)
            relevant = set(case.relevant_document_ids)
            rust_met = retrieval_metrics(rust_query, rust_docs, relevant, k_values=[1, 3])

            # The correct document should be at rank 1
            rust_top1 = rust_met["ranked_indices"][0] if rust_met["ranked_indices"] else -1
            status = RESULT_PASS if rust_top1 in relevant else RESULT_FAIL

            results.append(TestResult(
                test_id=tid, category="hard_negatives", status=status,
                metrics={"rust": rust_met, "rust_top1": rust_top1,
                         "relevant_ids": list(relevant)},
                note=f"top1={rust_top1} relevant={relevant}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="hard_negatives",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)

    return SuiteResult(
        name="04_hard_negatives",
        category="hard_negatives",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
    )


# ── 05 Multilingual ─────────────────────────────────────────────────────────


def run_multilingual(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Test multilingual and cross-language capabilities."""
    results: list[TestResult] = []

    # Cross-language pairs
    for case in MULTILINGUAL_PAIRS:
        tid = case.id
        try:
            rust_a = rust.embed_document(case.text_a)
            rust_b = rust.embed_document(case.text_b)
            rust_cos = cosine(rust_a, rust_b)

            rel = case.expected_relationship
            if rel == "cross_language":
                is_ok = rust_cos >= 0.5  # cross-language should be reasonably high
            elif rel == "related":
                is_ok = rust_cos >= 0.3
            else:
                is_ok = rust_cos < 0.6

            status = RESULT_PASS if is_ok else RESULT_WARNING
            results.append(TestResult(
                test_id=tid, category="multilingual", status=status,
                metrics={"rust_cosine": rust_cos, "expected_relationship": rel,
                         "language": case.language},
                note=f"lang={case.language} rel={rel} cos={rust_cos:.4f}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="multilingual",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    # Multilingual retrieval
    for case in MULTILINGUAL_RETRIEVAL:
        tid = case.id
        try:
            rust_query = rust.embed_query(case.query)
            rust_docs = rust.embed_batch(case.documents, is_query=False)
            relevant = set(case.relevant_document_ids)
            rust_met = retrieval_metrics(rust_query, rust_docs, relevant, k_values=[1, 3])

            rust_top1 = rust_met["ranked_indices"][0] if rust_met["ranked_indices"] else -1
            status = RESULT_PASS if rust_top1 in relevant else RESULT_FAIL
            results.append(TestResult(
                test_id=tid, category="multilingual_retrieval", status=status,
                metrics={"rust": rust_met, "rust_top1": rust_top1,
                         "language": case.language},
                note=f"lang={case.language} top1={rust_top1} relevant={relevant}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="multilingual_retrieval",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)
    warnings = sum(1 for r in results if r.status == RESULT_WARNING)

    return SuiteResult(
        name="05_multilingual",
        category="multilingual",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        warnings=warnings,
        results=results,
    )


# ── 06 NVDA Real-World ──────────────────────────────────────────────────────


def run_nvda_realworld(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Test retrieval with real-world NVDA/screen-reader text."""
    results: list[TestResult] = []

    for case in NVDA_REALWORLD_TEXTS:
        tid = case.id
        try:
            rust_query = rust.embed_query(case.query)
            rust_docs = rust.embed_batch(case.documents, is_query=False)
            relevant = set(case.relevant_document_ids)
            rust_met = retrieval_metrics(rust_query, rust_docs, relevant, k_values=[1, 3])

            rust_top1 = rust_met["ranked_indices"][0] if rust_met["ranked_indices"] else -1
            status = RESULT_PASS if rust_top1 in relevant else RESULT_FAIL

            results.append(TestResult(
                test_id=tid, category="nvda_realworld", status=status,
                metrics={"rust": rust_met, "rust_top1": rust_top1},
                note=f"top1={rust_top1} relevant={relevant} | {case.note}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="nvda_realworld",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)

    return SuiteResult(
        name="06_nvda_realworld",
        category="nvda_realworld",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
    )


# ── 07 Long Context ─────────────────────────────────────────────────────────


def run_long_context(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Test numerical parity and retrieval for long documents."""
    results: list[TestResult] = []

    # Parity at different lengths
    for item in LONG_CONTEXT_TEXTS:
        tid = item["id"]
        text = item["text"]
        try:
            hf_vec = hf.embed_document(text)
            rust_vec = rust.embed_document(text)
            comp = compare_embeddings(hf_vec, rust_vec)
            status = RESULT_PASS if comp["cosine"] >= 0.9999 else RESULT_FAIL
            results.append(TestResult(
                test_id=tid, category="long_context", status=status,
                metrics=comp,
                note=f"tokens≈{item['approx_tokens']} cos={comp['cosine']:.6f}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="long_context",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    # Position tests — relevant info at beginning vs end
    for case in LONG_CONTEXT_POSITION_TESTS:
        tid = case.id
        try:
            rust_query = rust.embed_query(case.query)
            rust_docs = rust.embed_batch(case.documents, is_query=False)
            relevant = set(case.relevant_document_ids)
            rust_met = retrieval_metrics(rust_query, rust_docs, relevant, k_values=[1, 3])

            rust_top1 = rust_met["ranked_indices"][0] if rust_met["ranked_indices"] else -1
            status = RESULT_PASS if rust_top1 in relevant else RESULT_WARNING
            results.append(TestResult(
                test_id=tid, category="long_context_position", status=status,
                metrics={"rust": rust_met, "rust_top1": rust_top1},
                note=f"top1={rust_top1} relevant={relevant} | {case.note}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="long_context_position",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)
    warnings = sum(1 for r in results if r.status == RESULT_WARNING)

    status = RESULT_FAIL if failed > 0 else (RESULT_WARNING if warnings > 0 else RESULT_PASS)
    return SuiteResult(
        name="07_long_context",
        category="long_context",
        status=status,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        warnings=warnings,
        results=results,
        note="Pay attention to 512→513 boundary (previous sliding-window bug)",
    )


# ── 08 Query/Document Behavior ──────────────────────────────────────────────


def run_query_document(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Verify query vs document embedding behavior is correct."""
    results: list[TestResult] = []

    test_texts = [
        "How do I change my Windows password?",
        "Python virtual environments isolate project dependencies.",
        "My Bluetooth headphones keep disconnecting.",
    ]

    for i, text in enumerate(test_texts):
        tid = f"qd_{i:03d}"

        try:
            # Correct usage
            rust_q = rust.embed_query(text)
            rust_d = rust.embed_document(text)
            hf_q = hf.embed_query(text)
            hf_d = hf.embed_document(text)

            # Query and doc embeddings of same text should be DIFFERENT
            # (because query has instruction prefix, doc doesn't)
            rust_qd_cos = cosine(rust_q, rust_d)
            hf_qd_cos = cosine(hf_q, hf_d)

            # They should not be identical
            is_different = rust_qd_cos < 0.9999
            status = RESULT_PASS if is_different else RESULT_FAIL

            results.append(TestResult(
                test_id=tid, category="query_document", status=status,
                metrics={
                    "rust_query_doc_cosine": rust_qd_cos,
                    "hf_query_doc_cosine": hf_qd_cos,
                },
                note=f"rust_qd_cos={rust_qd_cos:.6f} "
                     f"(should NOT be 1.0 — instruction prefix changes embedding)",
            ))

            # Cross-validation: Rust query ≈ HF query, Rust doc ≈ HF doc
            qq_cos = cosine(rust_q, hf_q)
            dd_cos = cosine(rust_d, hf_d)
            results.append(TestResult(
                test_id=f"qd_{i:03d}_cross",
                category="query_document",
                status=RESULT_PASS if qq_cos >= 0.9999 and dd_cos >= 0.9999 else RESULT_FAIL,
                metrics={"rust_hf_query_cos": qq_cos, "rust_hf_doc_cos": dd_cos},
                note=f"query_cos={qq_cos:.6f} doc_cos={dd_cos:.6f}",
            ))

        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="query_document",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)

    return SuiteResult(
        name="08_query_document",
        category="query_document",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
    )


# ── 09 Edge Cases ───────────────────────────────────────────────────────────


def run_edge_cases(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Test edge-case inputs for stability, no NaN/Inf, correct dimensions."""
    results: list[TestResult] = []

    for item in EDGE_CASES:
        tid = item["id"]
        text = item["text"]
        expected = item["expected_behavior"]

        if expected == "error_or_default":
            # Should raise ValueError or return gracefully
            try:
                vec = rust.embed_document(text)
                # If it didn't error, the vector should still be valid
                has_nan = any(math.isnan(x) for x in vec)
                has_inf = any(math.isinf(x) for x in vec)
                status = (
                    RESULT_PASS
                    if not has_nan and not has_inf and len(vec) == HARRIER_DIM
                    else RESULT_FAIL
                )
                results.append(TestResult(
                    test_id=tid, category="edge_cases", status=status,
                    metrics={"dim": len(vec), "norm": vector_norm(vec),
                             "has_nan": has_nan, "has_inf": has_inf},
                    note=f"whitespace/empty: returned vector (dim={len(vec)})",
                ))
            except ValueError:
                # Expected behavior for empty/whitespace
                results.append(TestResult(
                    test_id=tid, category="edge_cases", status=RESULT_PASS,
                    metrics={"error": "ValueError (expected)"},
                    note="Correctly raised ValueError for empty/whitespace input",
                ))
        else:
            try:
                vec = rust.embed_document(text)
                has_nan = any(math.isnan(x) for x in vec)
                has_inf = any(math.isinf(x) for x in vec)
                correct_dim = len(vec) == HARRIER_DIM
                norm = vector_norm(vec)

                issues = []
                if has_nan:
                    issues.append("NaN")
                if has_inf:
                    issues.append("Inf")
                if not correct_dim:
                    issues.append(f"wrong dim {len(vec)}")

                status = RESULT_PASS if not issues else RESULT_FAIL
                results.append(TestResult(
                    test_id=tid, category="edge_cases", status=status,
                    metrics={"dim": len(vec), "norm": norm,
                             "has_nan": has_nan, "has_inf": has_inf},
                    note="; ".join(issues) if issues else f"ok, norm={norm:.4f}",
                ))
            except Exception as exc:
                results.append(TestResult(
                    test_id=tid, category="edge_cases",
                    status=RESULT_FAIL, metrics={"error": str(exc)},
                ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)

    return SuiteResult(
        name="09_edge_cases",
        category="edge_cases",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
        note="Edge cases should produce no NaN/Inf, correct dim, stable norm.",
    )


# ── 10 Determinism ──────────────────────────────────────────────────────────


def run_determinism(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Verify deterministic output across repeated runs."""
    test_texts = [
        "Hello world, this is a deterministic test.",
        "How do I configure a Python virtual environment?",
        "NVDA is a free and open-source screen reader for Windows.",
        "मेरा नाम क्या है, यह एक परीक्षण है।",  # Hindi
        "The quick brown fox jumps over the lazy dog.",
    ]

    num_runs = 5
    all_rust_runs: list[list[list[float]]] = []

    for run in range(num_runs):
        # Note: we use embed_document to avoid instruction prefix differences
        vecs = rust.embed_batch(test_texts, is_query=False)
        all_rust_runs.append(vecs)

    det = is_deterministic(all_rust_runs)

    return SuiteResult(
        name="10_determinism",
        category="determinism",
        status=RESULT_PASS if det["deterministic"] else RESULT_FAIL,
        total_tests=det["num_comparisons"],
        passed=det["num_comparisons"] if det["deterministic"] else 0,
        failed=0 if det["deterministic"] else 1,
        results=[
            TestResult(
                test_id="det_001", category="determinism",
                status=RESULT_PASS if det["deterministic"] else RESULT_FAIL,
                metrics=det,
                note=f"max_diff={det['max_diff']:.2e} across {num_runs} runs",
            )
        ],
        distribution={"max_diff": det["max_diff"], "mean_diff": det["mean_diff"]},
    )


# ── 11 Performance ──────────────────────────────────────────────────────────


def run_performance(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Baseline performance measurements."""
    results: list[TestResult] = []
    perf_data: dict[str, Any] = {}

    # Model load time (measured during warm_up)
    # First inference
    short_text = "Hello world, this is a performance test."
    medium_text = (
        "Python is a high-level programming language known for its readability "
        "and versatility. It supports multiple programming paradigms including "
        "procedural, object-oriented, and functional programming. " * 5
    )
    long_text = medium_text * 10

    for name, text in [("short", short_text), ("medium", medium_text), ("long", long_text)]:
        # Warm inference
        _, warm_timer = time_it(f"rust_{name}_warm", rust.embed_document, text)

        # Measure throughput over 5 runs
        times: list[float] = []
        for _ in range(5):
            _, t = time_it(f"rust_{name}", rust.embed_document, text)
            times.append(t.elapsed_seconds)

        perf_data[f"rust_{name}_warm_ms"] = warm_timer.elapsed_seconds * 1000
        perf_data[f"rust_{name}_mean_ms"] = (sum(times) / len(times)) * 1000
        perf_data[f"rust_{name}_min_ms"] = min(times) * 1000
        perf_data[f"rust_{name}_max_ms"] = max(times) * 1000

    results.append(TestResult(
        test_id="perf_001", category="performance",
        status=RESULT_NA,  # Not pass/fail, just baseline
        metrics=perf_data,
        note="Baseline performance — not a pass/fail test",
    ))

    return SuiteResult(
        name="11_performance",
        category="performance",
        status=RESULT_NA,
        total_tests=1,
        results=results,
        distribution=perf_data,
    )


# ── 12 Failure Tests ────────────────────────────────────────────────────────


def run_failure_tests(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Intentionally test scenarios where the model SHOULD struggle."""
    results: list[TestResult] = []

    failure_cases = [
        {
            "id": "fail_001",
            "query": "fix it",
            "docs": [
                "How to fix a leaking pipe in your bathroom.",
                "How to fix a corrupted Windows registry entry.",
                "How to fix a broken zipper on your jacket.",
            ],
            "relevant": [1],  # ambiguous query
            "note": "Ambiguous query — model may not predict correctly",
        },
        {
            "id": "fail_002",
            "query": "What is the capital of Burkina Faso?",
            "docs": [
                "Python is a programming language created by Guido van Rossum.",
                "The quick brown fox jumps over the lazy dog.",
                "NVDA screen reader supports Windows 10 and 11.",
            ],
            "relevant": [],
            "note": "Query about factual knowledge not present in documents",
        },
        {
            "id": "fail_003",
            "query": "S",
            "docs": [
                "The letter S is the 19th letter of the English alphabet.",
                "S is used as an abbreviation for South.",
                "In chemistry, S represents the element sulfur.",
            ],
            "relevant": [0, 1, 2],
            "note": "Extremely short query — embedding may be poor",
        },
    ]

    for case in failure_cases:
        tid = case["id"]
        try:
            rust_query = rust.embed_query(case["query"])
            rust_docs = rust.embed_batch(case["docs"], is_query=False)
            relevant = set(case["relevant"])
            rust_met = retrieval_metrics(rust_query, rust_docs, relevant, k_values=[1, 3])

            # These are EXPECTED to potentially fail
            # Mark as WARNING (informational) rather than FAIL
            rust_top1 = rust_met["ranked_indices"][0] if rust_met["ranked_indices"] else -1
            status = RESULT_WARNING  # Informational only

            results.append(TestResult(
                test_id=tid, category="failure_tests", status=status,
                metrics={"rust": rust_met, "rust_top1": rust_top1},
                note=case["note"],
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="failure_tests",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    return SuiteResult(
        name="12_failure_tests",
        category="failure_tests",
        status=RESULT_NA,  # These are informational
        total_tests=len(results),
        warnings=len(results),
        results=results,
        note="These test model limitations — failures are expected and informational.",
    )


# ── 13 Ranking Consistency ──────────────────────────────────────────────────


def run_ranking_consistency(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Compare HF and Rust retrieval rankings for identical queries."""
    results: list[TestResult] = []
    dataset = RETRIEVAL_TECH_DOCS

    hf_docs = hf.embed_batch(dataset.documents, is_query=False)
    rust_docs = rust.embed_batch(dataset.documents, is_query=False)

    agreement_data: dict[str, list[float]] = {
        "top1_agree": [], "top3_overlap": [], "top5_overlap": [], "top10_overlap": [],
    }
    ktaus: list[float] = []

    for qi, qdata in enumerate(dataset.queries):
        query_text = qdata["query"]
        tid = f"rank_{qi:03d}"

        try:
            hf_query = hf.embed_query(query_text)
            rust_query = rust.embed_query(query_text)

            hf_met = retrieval_metrics(hf_query, hf_docs, set(), k_values=[1])
            rust_met = retrieval_metrics(rust_query, rust_docs, set(), k_values=[1])

            hf_ranked = hf_met["ranked_indices"]
            rust_ranked = rust_met["ranked_indices"]

            t1agree = top1_agreement(hf_ranked, rust_ranked)
            agreement_data["top1_agree"].append(1.0 if t1agree else 0.0)

            for k in [3, 5, 10]:
                overlap = ranking_overlap(hf_ranked, rust_ranked, k)
                agreement_data[f"top{k}_overlap"].append(overlap[f"top{k}_overlap"])

            kt = kendall_tau(hf_ranked[:50], rust_ranked[:50])
            ktaus.append(kt)

            status = RESULT_PASS if t1agree else RESULT_WARNING
            results.append(TestResult(
                test_id=tid, category="ranking_consistency", status=status,
                metrics={
                    "top1_agree": t1agree,
                    "top3_overlap": agreement_data["top3_overlap"][-1],
                    "top5_overlap": agreement_data["top5_overlap"][-1],
                    "top10_overlap": agreement_data["top10_overlap"][-1],
                    "kendall_tau": kt,
                },
                note=f"top1={'OK' if t1agree else 'MISMATCH'} ktau={kt:.4f}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="ranking_consistency",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)
    warnings = sum(1 for r in results if r.status == RESULT_WARNING)

    dist = {}
    for key, vals in agreement_data.items():
        if vals:
            dist[key] = compute_distribution(vals)
    if ktaus:
        dist["kendall_tau"] = compute_distribution(ktaus)

    return SuiteResult(
        name="13_ranking_consistency",
        category="ranking_consistency",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        warnings=warnings,
        results=results,
        distribution=dist,
    )


# ── 14 Threshold Calibration ────────────────────────────────────────────────


def run_threshold_calibration(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Collect cosine distributions for different relationship types."""
    # Re-use semantic pairs data
    all_cosines: dict[str, list[float]] = {
        "exact_match": [], "paraphrase": [], "related": [],
        "hard_negative": [], "unrelated": [],
    }

    for case in SEMANTIC_POSITIVE_PAIRS:
        try:
            rust_a = rust.embed_document(case.text_a)
            rust_b = rust.embed_document(case.text_b)
            rust_cos = cosine(rust_a, rust_b)
            all_cosines.setdefault(case.expected_relationship, []).append(rust_cos)
        except Exception:
            pass

    distributions = {
        rel: compute_distribution(vals)
        for rel, vals in all_cosines.items() if vals
    }

    # Check for problematic overlap between categories
    overlap_notes: list[str] = []
    if "paraphrase" in distributions and "unrelated" in distributions:
        p95_para = distributions["paraphrase"].get("p5", 0)
        p5_unrel = distributions["unrelated"].get("p95", 1)
        if p95_para < p5_unrel:
            overlap_notes.append(
                "Good separation: paraphrase p5 > unrelated p95"
            )
        else:
            overlap_notes.append(
                f"Overlap warning: paraphrase p5={p95_para:.3f} vs unrelated p95={p5_unrel:.3f}"
            )

    return SuiteResult(
        name="14_threshold_calibration",
        category="threshold_calibration",
        status=RESULT_NA,  # Informational
        total_tests=len(all_cosines),
        distribution=distributions,
        note="; ".join(overlap_notes) if overlap_notes else "Distributions collected.",
    )


# ── 15 Regression Tests ─────────────────────────────────────────────────────


def run_regression_tests(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> SuiteResult:
    """Regression tests for previously-fixed bugs."""
    results: list[TestResult] = []

    for case in REGRESSION_TESTS:
        tid = case.id
        try:
            rust_a = rust.embed_document(case.text_a)
            rust_b = rust.embed_document(case.text_b)
            rust_cos = cosine(rust_a, rust_b)

            # Regression tests just verify no crash and reasonable output
            has_nan = any(math.isnan(x) for x in rust_a) or any(math.isnan(x) for x in rust_b)
            has_inf = any(math.isinf(x) for x in rust_a) or any(math.isinf(x) for x in rust_b)
            correct_dim = len(rust_a) == HARRIER_DIM and len(rust_b) == HARRIER_DIM

            issues = []
            if has_nan:
                issues.append("NaN")
            if has_inf:
                issues.append("Inf")
            if not correct_dim:
                issues.append(f"dim={len(rust_a)}")

            status = RESULT_PASS if not issues else RESULT_FAIL
            results.append(TestResult(
                test_id=tid, category="regression", status=status,
                metrics={"cosine": rust_cos, "dim": len(rust_a)},
                note=f"{case.note} | cos={rust_cos:.6f}",
            ))
        except Exception as exc:
            results.append(TestResult(
                test_id=tid, category="regression",
                status=RESULT_FAIL, metrics={"error": str(exc)},
            ))

    passed = sum(1 for r in results if r.status == RESULT_PASS)
    failed = sum(1 for r in results if r.status == RESULT_FAIL)

    return SuiteResult(
        name="15_regression",
        category="regression",
        status=RESULT_PASS if failed == 0 else RESULT_FAIL,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        results=results,
    )


# ── Master runner ───────────────────────────────────────────────────────────


def run_all_suites(
    hf: HFHarrierRunner, rust: RustHarrierRunner
) -> list[SuiteResult]:
    """Run all validation suites and return results."""
    suites: list[SuiteResult] = []

    # Pre-warm
    hf.warm_up()
    rust.warm_up()

    suite_runners = [
        ("01_numerical_parity", run_numerical_parity),
        ("02_semantic_similarity", run_semantic_similarity),
        ("03_retrieval", run_retrieval),
        ("04_hard_negatives", run_hard_negatives),
        ("05_multilingual", run_multilingual),
        ("06_nvda_realworld", run_nvda_realworld),
        ("07_long_context", run_long_context),
        ("08_query_document", run_query_document),
        ("09_edge_cases", run_edge_cases),
        ("10_determinism", run_determinism),
        ("11_performance", run_performance),
        ("12_failure_tests", run_failure_tests),
        ("13_ranking_consistency", run_ranking_consistency),
        ("14_threshold_calibration", run_threshold_calibration),
        ("15_regression", run_regression_tests),
    ]

    for name, runner in suite_runners:
        try:
            result, timer = time_it(name, runner, hf, rust)
            result.timing = timer
            suites.append(result)
        except Exception as exc:
            suites.append(SuiteResult(
                name=name,
                category=name,
                status=RESULT_FAIL,
                note=f"Suite crashed: {exc}",
            ))

    return suites
