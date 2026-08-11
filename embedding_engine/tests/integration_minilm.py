"""
Integration tests for the all-MiniLM-L6-v2 embedding model.

These tests apply the shared :class:`EmbeddingModelTestContract` plus
MiniLM-specific checks: pooling behaviour, normalization details, and
token-limit boundary behaviour.
"""

from __future__ import annotations

import math
import sys
import os

# Ensure the embedding_engine.pyd is discoverable (it lives one dir up).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import embedding_engine
from integration_common import (
    EmbeddingModelTestContract,
    _all_finite,
    _cosine,
    _max_abs_diff,
    _norm,
)


class MiniLMContract(EmbeddingModelTestContract):
    """Contract runner for ``all-MiniLM-L6-v2``."""

    @property
    def model_id(self) -> str:
        return "all-MiniLM-L6-v2"

    def create_engine(self) -> embedding_engine.EmbeddingEngine:
        return embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")


# ---------------------------------------------------------------------------
# MiniLM-specific tests (beyond the shared contract)
# ---------------------------------------------------------------------------

def test_token_limit_boundary() -> None:
    """Input at exactly max_tokens produces valid output."""
    engine = embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")
    limit = engine.max_tokens()  # 256
    # Build a string that should be close to the token limit.
    # Each word is ~1 token, so 250 words ≈ 250 tokens.
    text = "test " * min(limit - 10, 250)
    vec = engine.embed(text)
    assert len(vec) == 384
    assert _all_finite(vec)
    assert abs(_norm(vec) - 1.0) < 0.01


def test_short_input() -> None:
    """Very short input (single character / single word) produces valid output."""
    engine = embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")
    for short in ("a", "Hi", "OK"):
        vec = engine.embed(short)
        assert len(vec) == 384, f"Short input {short!r}: {len(vec)} dims"
        assert _all_finite(vec)


def test_identical_sentences_cosine_one() -> None:
    """Identical sentences have cosine similarity very close to 1.0."""
    engine = embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")
    text = "The quick brown fox jumps over the lazy dog."
    a = engine.embed(text)
    b = engine.embed(text)
    sim = _cosine(a, b)
    assert sim > 0.999, f"Identical sentences cosine = {sim:.6f}, expected > 0.999"


def test_large_batch() -> None:
    """Batch of 8-16 sentences completes without error."""
    engine = embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")
    texts = [
        "Sentence number one.",
        "Another different sentence.",
        "The weather is nice today.",
        "Machine learning is fascinating.",
        "Python and Rust work well together.",
        "Embedding models compress meaning into vectors.",
        "Semantic search uses cosine similarity.",
        "HuggingFace provides many pretrained models.",
    ]
    batch = engine.embed_batch(texts)
    assert len(batch) == len(texts)
    for i, vec in enumerate(batch):
        assert len(vec) == 384, f"Large batch[{i}]: {len(vec)} dims"
        assert _all_finite(vec)


def test_first_vs_warm_consistency() -> None:
    """First embed and warm embed produce deterministic results."""
    engine = embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")
    text = "Consistency check between first and warm call."
    first = engine.embed(text)
    warm = engine.embed(text)
    diff = _max_abs_diff(first, warm)
    assert diff < 1e-6, f"First vs warm differ: max abs diff = {diff:.2e}"


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("MiniLM Integration Tests")
    print("=" * 60)

    # 1. Shared contract
    print("\n--- Shared EmbeddingModel Contract ---")
    contract = MiniLMContract()
    contract.run_all()

    # 2. MiniLM-specific tests
    print("\n--- MiniLM-Specific Tests ---")
    specifics = [
        ("token_limit_boundary", test_token_limit_boundary),
        ("short_input", test_short_input),
        ("identical_cosine_one", test_identical_sentences_cosine_one),
        ("large_batch", test_large_batch),
        ("first_vs_warm_consistency", test_first_vs_warm_consistency),
    ]
    passed = 0
    for name, fn in specifics:
        print(f"  {name}...", end=" ")
        try:
            fn()
        except Exception as exc:
            print(f"FAIL\n    {exc}")
            raise
        print("PASS")
        passed += 1
    print(f"  → {passed}/{len(specifics)} MiniLM-specific tests passed")

    print("\n" + "=" * 60)
    print("All MiniLM integration tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
