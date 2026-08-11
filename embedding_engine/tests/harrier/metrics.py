"""
Metrics for evaluating embedding model quality and retrieval performance.

All functions operate on list[float] vectors or list[list[float]] matrices.
No external ML library required — pure Python with math.
"""

from __future__ import annotations

import math
from typing import Any


# ── Basic vector operations ──────────────────────────────────────────────────


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def l2_distance(a: list[float], b: list[float]) -> float:
    """Euclidean (L2) distance between two vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def max_abs_diff(a: list[float], b: list[float]) -> float:
    """Maximum element-wise absolute difference."""
    return max(abs(x - y) for x, y in zip(a, b))


def mean_abs_diff(a: list[float], b: list[float]) -> float:
    """Mean element-wise absolute difference."""
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def vector_norm(vec: list[float]) -> float:
    """L2 norm of a vector."""
    return math.sqrt(sum(x * x for x in vec))


# ── Distribution statistics ──────────────────────────────────────────────────


def compute_distribution(values: list[float]) -> dict[str, float]:
    """Compute distribution statistics for a list of values."""
    if not values:
        return {
            "count": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0,
            "std": 0.0, "p1": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0,
        }
    n = len(values)
    sorted_vals = sorted(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n

    def percentile(p: float) -> float:
        idx = p / 100.0 * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    return {
        "count": n,
        "mean": mean,
        "median": percentile(50),
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "std": math.sqrt(variance),
        "p1": percentile(1),
        "p5": percentile(5),
        "p50": percentile(50),
        "p95": percentile(95),
        "p99": percentile(99),
    }


# ── Numerical comparison (HF vs Rust) ────────────────────────────────────────


def compare_embeddings(
    ref: list[float], rust: list[float]
) -> dict[str, float]:
    """Compare a single pair of HF and Rust embeddings."""
    assert len(ref) == len(rust), f"Dimension mismatch: {len(ref)} vs {len(rust)}"
    return {
        "cosine": cosine(ref, rust),
        "l2_distance": l2_distance(ref, rust),
        "max_abs_diff": max_abs_diff(ref, rust),
        "mean_abs_diff": mean_abs_diff(ref, rust),
        "ref_norm": vector_norm(ref),
        "rust_norm": vector_norm(rust),
    }


def compare_all_embeddings(
    refs: list[list[float]], rusts: list[list[float]]
) -> dict[str, Any]:
    """Compare multiple pairs and return aggregate statistics."""
    results = [compare_embeddings(r, ru) for r, ru in zip(refs, rusts)]
    cosines = [r["cosine"] for r in results]
    return {
        "comparisons": results,
        "cosine_distribution": compute_distribution(cosines),
        "l2_distribution": compute_distribution([r["l2_distance"] for r in results]),
        "max_abs_diff_distribution": compute_distribution([r["max_abs_diff"] for r in results]),
    }


# ── Retrieval metrics ────────────────────────────────────────────────────────


def _rank_by_cosine(
    query_vec: list[float], doc_vecs: list[list[float]]
) -> list[tuple[int, float]]:
    """Rank document indices by descending cosine similarity to query."""
    scored = [(i, cosine(query_vec, dv)) for i, dv in enumerate(doc_vecs)]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def recall_at_k(
    ranked: list[tuple[int, float]],
    relevant_ids: set[int],
    k: int,
) -> float:
    """Recall@k: fraction of relevant docs in top-k results."""
    if not relevant_ids:
        return 0.0
    top_k_ids = {idx for idx, _ in ranked[:k]}
    return len(top_k_ids & relevant_ids) / len(relevant_ids)


def precision_at_k(
    ranked: list[tuple[int, float]],
    relevant_ids: set[int],
    k: int,
) -> float:
    """Precision@k: fraction of top-k results that are relevant."""
    if k == 0:
        return 0.0
    top_k_ids = {idx for idx, _ in ranked[:k]}
    return len(top_k_ids & relevant_ids) / k


def mrr(
    ranked: list[tuple[int, float]],
    relevant_ids: set[int],
) -> float:
    """Mean Reciprocal Rank: 1/rank of first relevant document."""
    for rank, (idx, _) in enumerate(ranked, start=1):
        if idx in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked: list[tuple[int, float]],
    relevant_ids: set[int],
    k: int,
) -> float:
    """Normalized Discounted Cumulative Gain at k (binary relevance)."""
    # DCG
    dcg = 0.0
    for i, (idx, _) in enumerate(ranked[:k], start=1):
        if idx in relevant_ids:
            dcg += 1.0 / math.log2(i + 1)

    # IDCG (ideal: all relevant docs at top)
    ideal_count = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_count + 1))

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def retrieval_metrics(
    query_vec: list[float],
    doc_vecs: list[list[float]],
    relevant_ids: set[int],
    k_values: list[int] | None = None,
) -> dict[str, Any]:
    """Compute full retrieval metrics for a single query."""
    if k_values is None:
        k_values = [1, 3, 5, 10]

    ranked = _rank_by_cosine(query_vec, doc_vecs)
    return {
        "ranked_indices": [idx for idx, _ in ranked],
        "ranked_scores": [score for _, score in ranked],
        **{f"recall@{k}": recall_at_k(ranked, relevant_ids, k) for k in k_values},
        **{f"precision@{k}": precision_at_k(ranked, relevant_ids, k) for k in k_values},
        "mrr": mrr(ranked, relevant_ids),
        **{f"ndcg@{k}": ndcg_at_k(ranked, relevant_ids, k) for k in k_values},
    }


# ── Ranking agreement (HF vs Rust) ───────────────────────────────────────────


def ranking_overlap(
    hf_ranked: list[int], rust_ranked: list[int], k: int
) -> dict[str, float]:
    """Compute ranking agreement metrics at k."""
    hf_top = set(hf_ranked[:k])
    rust_top = set(rust_ranked[:k])
    intersection = hf_top & rust_top
    return {
        f"top{k}_overlap": len(intersection) / k if k > 0 else 0.0,
        f"top{k}_agreement": 1.0 if hf_top == rust_top else 0.0,
    }


def top1_agreement(
    hf_ranked: list[int], rust_ranked: list[int]
) -> bool:
    """Check if top-1 result is identical."""
    return hf_ranked[0] == rust_ranked[0] if hf_ranked and rust_ranked else False


def kendall_tau(
    a: list[int], b: list[int]
) -> float:
    """Kendall tau rank correlation between two rankings."""
    n = len(a)
    if n < 2:
        return 0.0
    pos_a = {item: i for i, item in enumerate(a)}
    pos_b = {item: i for i, item in enumerate(b)}
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            ai, aj = a[i], a[j]
            bj_val = b[j]
            if pos_a[ai] < pos_a[aj] and pos_b[ai] < pos_b[bj_val]:
                concordant += 1
            elif pos_a[ai] > pos_a[aj] and pos_b[ai] > pos_b[bj_val]:
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total > 0 else 0.0


# ── Helper ────────────────────────────────────────────────────────────────────


def is_deterministic(
    all_vectors: list[list[list[float]]]
) -> dict[str, Any]:
    """Check that repeated runs produce identical vectors.

    Args:
        all_vectors: list of runs, each run is list of vectors for each input.
    """
    if len(all_vectors) < 2:
        return {"deterministic": True, "max_diff": 0.0, "note": "Only one run"}

    max_diff = 0.0
    diffs: list[float] = []
    for input_idx in range(len(all_vectors[0])):
        ref_vec = all_vectors[0][input_idx]
        for run_idx in range(1, len(all_vectors)):
            diff = max_abs_diff(ref_vec, all_vectors[run_idx][input_idx])
            diffs.append(diff)
            max_diff = max(max_diff, diff)

    return {
        "deterministic": max_diff < 1e-6,
        "max_diff": max_diff,
        "mean_diff": sum(diffs) / len(diffs) if diffs else 0.0,
        "num_comparisons": len(diffs),
    }
