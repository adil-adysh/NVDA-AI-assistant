"""
Shared integration test contract for all embedding models.

Every model registered in the embedding engine MUST pass this contract.
Import :class:`EmbeddingModelTestContract` and call its methods from
model-specific integration tests (e.g. ``integration_minilm.py``).

Tests are structured as individual public methods so failures produce
clear, targeted error messages.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

import embedding_engine


# ---------------------------------------------------------------------------
# Helper utilities shared across integration tests
# ---------------------------------------------------------------------------

def _norm(vec: list[float]) -> float:
    """L2 norm of a vector."""
    return math.sqrt(sum(x * x for x in vec))


def _max_abs_diff(a: list[float], b: list[float]) -> float:
    """Maximum element-wise absolute difference between two equal-length vectors."""
    assert len(a) == len(b), f"Vector length mismatch: {len(a)} vs {len(b)}"
    return max(abs(x - y) for x, y in zip(a, b))


def _all_finite(vec: list[float]) -> bool:
    """True if every element in *vec* is finite (not NaN, not Inf)."""
    return all(math.isfinite(x) for x in vec)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (_norm(a) * _norm(b))


# ---------------------------------------------------------------------------
# Unicode test cases – exercises the full pipeline for scripts beyond ASCII
# ---------------------------------------------------------------------------

UNICODE_TEXTS: list[str] = [
    "Hello world",
    "नमस्ते दुनिया",
    "ગુજરાતી લખાણ",
    "مرحبا بالعالم",
    "こんにちは世界",
    "émojis and café",
]


# ---------------------------------------------------------------------------
# EmbeddingModelTestContract
# ---------------------------------------------------------------------------

class EmbeddingModelTestContract(ABC):
    """Contract that every embedding model must satisfy.

    Subclasses must override :meth:`model_id` (property) and
    :meth:`create_engine` (factory).  All test methods are called
    automatically by :meth:`run_all`.

    Each test method is public so callers can run them individually
    (e.g. ``contract.test_deterministic()``).
    """

    # ── subclass contract ──────────────────────────────────────────────

    @property
    @abstractmethod
    def model_id(self) -> str:
        """The HuggingFace model ID under test."""
        ...

    @abstractmethod
    def create_engine(self) -> embedding_engine.EmbeddingEngine:
        """Create a fresh engine instance for the model under test."""
        ...

    # ── expected dimensions / tokens – override if not standard ────────

    @property
    def expected_dim(self) -> int:
        """Expected embedding dimension. Override if model-specific check needed."""
        info = embedding_engine.EmbeddingEngine.model_info(self.model_id)
        assert info is not None, f"Model {self.model_id!r} not found in registry"
        return info["dimensions"]

    @property
    def expected_max_tokens(self) -> int:
        """Expected max tokens. Override if model-specific check needed."""
        info = embedding_engine.EmbeddingEngine.model_info(self.model_id)
        assert info is not None, f"Model {self.model_id!r} not found in registry"
        return info["max_tokens"]

    @property
    def normalize_output(self) -> bool:
        """Whether this model is expected to produce L2-normalized vectors."""
        return True

    # ── tolerances ─────────────────────────────────────────────────────

    DETERMINISM_TOLERANCE: float = 1e-6
    NORM_TOLERANCE: float = 0.01
    BATCH_EQUIVALENCE_TOLERANCE: float = 1e-5

    # ── test methods ───────────────────────────────────────────────────

    def test_registered(self) -> None:
        """Model ID appears in ``available_models()``."""
        models = embedding_engine.EmbeddingEngine.available_models()
        assert self.model_id in models, f"{self.model_id!r} not in {models}"

    def test_metadata(self) -> None:
        """``model_info()`` returns a dict with required keys."""
        info = embedding_engine.EmbeddingEngine.model_info(self.model_id)
        assert info is not None, f"No metadata for {self.model_id!r}"
        assert isinstance(info, dict), f"Expected dict, got {type(info)}"
        for key in ("id", "dimensions", "max_tokens", "architecture"):
            assert key in info, f"Missing key {key!r} in model_info"

    def test_engine_construction(self) -> None:
        """Engine creates without error and responds to ping."""
        engine = self.create_engine()
        assert engine.ping() == "embedding_engine ready"

    def test_dimensions(self) -> None:
        """``engine.dimensions()`` returns the expected value."""
        engine = self.create_engine()
        assert engine.dimensions() == self.expected_dim, (
            f"Expected {self.expected_dim} dims, got {engine.dimensions()}"
        )

    def test_max_tokens(self) -> None:
        """``engine.max_tokens()`` reports the expected cap."""
        engine = self.create_engine()
        assert engine.max_tokens() == self.expected_max_tokens, (
            f"Expected {self.expected_max_tokens} tokens, got {engine.max_tokens()}"
        )

    def test_single_embed(self) -> None:
        """Single-text embedding produces correct-dimension output."""
        engine = self.create_engine()
        vec = engine.embed("Hello world, this is a test sentence.")
        assert len(vec) == self.expected_dim, (
            f"Expected {self.expected_dim} dims, got {len(vec)}"
        )

    def test_finite_values(self) -> None:
        """Embedding contains only finite (non-NaN, non-Inf) values."""
        engine = self.create_engine()
        vec = engine.embed("Finite check: 1, 2, 3.")
        assert _all_finite(vec), f"Non-finite values in embedding: {vec[:10]}..."

    def test_normalized(self) -> None:
        """Embedding is L2-normalized (if model contract requires it)."""
        if not self.normalize_output:
            return  # skip — this model does not promise normalization
        engine = self.create_engine()
        vec = engine.embed("Normalization test sentence.")
        n = _norm(vec)
        assert abs(n - 1.0) < self.NORM_TOLERANCE, (
            f"Expected unit norm, got {n:.6f}"
        )

    def test_deterministic(self) -> None:
        """Identical input twice → identical output (within tolerance)."""
        engine = self.create_engine()
        text = "The quick brown fox jumps over the lazy dog."
        a = engine.embed(text)
        b = engine.embed(text)
        diff = _max_abs_diff(a, b)
        assert diff < self.DETERMINISM_TOLERANCE, (
            f"Non-deterministic output: max element-wise diff = {diff:.2e}"
        )

    def test_empty_input(self) -> None:
        """Empty or whitespace-only input is rejected by the engine.

        The engine raises ``ValueError`` for empty/whitespace-only input.
        Callers must validate or pre-process text before calling ``embed()``.
        """
        engine = self.create_engine()
        for invalid in ("", "   ", "\t\n  "):
            try:
                engine.embed(invalid)
            except ValueError:
                pass  # expected — engine rejects empty/whitespace input
            except Exception as exc:
                raise AssertionError(
                    f"Expected ValueError for {invalid!r}, got {type(exc).__name__}: {exc}"
                ) from exc
            else:
                raise AssertionError(
                    f"Expected ValueError for {invalid!r}, but embed() succeeded"
                )

    def test_unicode(self) -> None:
        """Unicode texts (various scripts) do not crash and produce valid vectors.

        This tests pipeline correctness, NOT multilingual model quality.
        """
        engine = self.create_engine()
        for text in UNICODE_TEXTS:
            vec = engine.embed(text)
            assert len(vec) == self.expected_dim, (
                f"Unicode text {text!r} produced {len(vec)} dims"
            )
            assert _all_finite(vec), (
                f"Unicode text {text!r} produced non-finite values"
            )
            if self.normalize_output:
                n = _norm(vec)
                assert abs(n - 1.0) < self.NORM_TOLERANCE, (
                    f"Unicode text {text!r} produced norm {n:.6f}"
                )

    def test_long_input(self) -> None:
        """Input exceeding ``max_tokens`` is handled gracefully.

        The engine exposes ``max_tokens()`` as a contract.  This test
        verifies the engine does not panic/crash on long input.  The
        policy (truncate vs. reject) is documented but not dictated here.
        """
        engine = self.create_engine()
        limit = engine.max_tokens()
        # Build a string that's ~10× the token limit in words.
        long_text = "word " * (limit * 10)
        try:
            vec = engine.embed(long_text)
        except Exception as exc:
            # Engine may choose to reject.  Either way, no crash = pass.
            print(f"  (long input rejected: {exc})")
            return
        # If the engine produced output, it must still be valid.
        assert len(vec) == self.expected_dim, (
            f"Long input produced {len(vec)} dims"
        )
        assert _all_finite(vec), "Long input produced non-finite values"

    def test_batch_embed(self) -> None:
        """Batch embedding returns one vector per input text."""
        engine = self.create_engine()
        texts = ["First sentence.", "Second sentence.", "Third one here."]
        batch = engine.embed_batch(texts)
        assert len(batch) == len(texts), (
            f"Expected {len(texts)} vectors, got {len(batch)}"
        )
        for i, vec in enumerate(batch):
            assert len(vec) == self.expected_dim, (
                f"Batch[{i}] wrong dim: {len(vec)}"
            )
            assert _all_finite(vec), f"Batch[{i}] has non-finite values"

    def test_batch_equals_single(self) -> None:
        """Each batch result matches the corresponding single-text embed."""
        engine = self.create_engine()
        texts = [
            "First benchmark sentence for batch equivalence.",
            "Second sentence, different from the first.",
            "A third example with different words entirely.",
        ]
        singles = [engine.embed(t) for t in texts]
        batch = engine.embed_batch(texts)
        for i, (single_vec, batch_vec) in enumerate(zip(singles, batch)):
            diff = _max_abs_diff(single_vec, batch_vec)
            assert diff < self.BATCH_EQUIVALENCE_TOLERANCE, (
                f"Batch[{i}] diverges from single: max diff = {diff:.2e}"
            )

    def test_semantic_sanity(self) -> None:
        """Similar sentences are closer than unrelated sentences.

        This is a directional check (similar > unrelated), NOT a
        hard-coded threshold.  Model-quality evaluation belongs in
        the benchmark suite.
        """
        engine = self.create_engine()
        similar_a = "The quick brown fox jumps over the lazy dog."
        similar_b = "A fast brown fox leaped over a sleepy canine."
        unrelated = "Machine learning models require large amounts of training data."

        emb_sim_a = engine.embed(similar_a)
        emb_sim_b = engine.embed(similar_b)
        emb_unr = engine.embed(unrelated)

        # Finite check before similarity
        for label, vec in [("similar_a", emb_sim_a), ("similar_b", emb_sim_b), ("unrelated", emb_unr)]:
            assert _all_finite(vec), f"Non-finite values in {label}"

        sim_score = _cosine(emb_sim_a, emb_sim_b)
        unr_score = _cosine(emb_sim_a, emb_unr)
        assert sim_score > unr_score, (
            f"Similar ({sim_score:.4f}) not greater than unrelated ({unr_score:.4f})"
        )

    # ── runner ─────────────────────────────────────────────────────────

    def run_all(self) -> None:
        """Run every contract test and print a summary.

        Stops at the first failure (fail-fast).
        """
        tests = [
            ("registered", self.test_registered),
            ("metadata", self.test_metadata),
            ("engine_construction", self.test_engine_construction),
            ("dimensions", self.test_dimensions),
            ("max_tokens", self.test_max_tokens),
            ("single_embed", self.test_single_embed),
            ("finite_values", self.test_finite_values),
            ("normalized", self.test_normalized),
            ("deterministic", self.test_deterministic),
            ("empty_input", self.test_empty_input),
            ("unicode", self.test_unicode),
            ("long_input", self.test_long_input),
            ("batch_embed", self.test_batch_embed),
            ("batch_equals_single", self.test_batch_equals_single),
            ("semantic_sanity", self.test_semantic_sanity),
        ]
        passed = 0
        for name, fn in tests:
            print(f"  [{self.model_id}] {name}...", end=" ")
            try:
                fn()
            except Exception as exc:
                print(f"FAIL\n    {exc}")
                raise
            print("PASS")
            passed += 1
        print(f"  → {passed}/{len(tests)} contract tests passed")
