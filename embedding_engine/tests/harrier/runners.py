"""
Reference and Rust/Candle embedding runners for Harrier validation.

Provides:
- ``HFHarrierRunner`` — runs the official HuggingFace model via sentence-transformers
- ``RustHarrierRunner`` — runs our Rust/Candle implementation via embedding_engine

Both produce normalized (L2=1) float vectors of dimension 640.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any


# ── Constants ────────────────────────────────────────────────────────────────

HARRIER_MODEL_ID = "harrier-oss-v1-270m"
HARRIER_REPO = "microsoft/harrier-oss-v1-270m"
HARRIER_DIM = 640

# Official Harrier instruction prefix for query mode
QUERY_INSTRUCTION = (
    "Given a web search query, retrieve relevant passages that answer the query"
)


def _normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector in-place (returns new list)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec[:]
    return [x / norm for x in vec]


def _all_finite(vec: list[float]) -> bool:
    """True if all elements are finite."""
    return all(math.isfinite(x) for x in vec)


# ── HF Reference Runner ──────────────────────────────────────────────────────


@dataclass
class HFHarrierRunner:
    """Runs the official HuggingFace Harrier model via sentence-transformers."""

    model: Any = None  # SentenceTransformer, lazy-loaded

    def _ensure_loaded(self) -> None:
        if self.model is not None:
            return
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(
            HARRIER_REPO,
            model_kwargs={"dtype": "auto"},
            device="cpu",
        )

    def embed_query(self, text: str) -> list[float]:
        """Embed a query with the Harrier instruction prefix."""
        self._ensure_loaded()
        formatted = f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}"
        embeddings = self.model.encode(
            [formatted], normalize_embeddings=True, show_progress_bar=False
        )
        result: list[float] = embeddings[0].tolist()
        return result

    def embed_document(self, text: str) -> list[float]:
        """Embed a document (no instruction prefix)."""
        self._ensure_loaded()
        embeddings = self.model.encode(
            [text], normalize_embeddings=True, show_progress_bar=False
        )
        result: list[float] = embeddings[0].tolist()
        return result

    def embed_batch(
        self, texts: list[str], is_query: bool = False
    ) -> list[list[float]]:
        """Embed a batch of texts."""
        self._ensure_loaded()
        if is_query:
            formatted = [
                f"Instruct: {QUERY_INSTRUCTION}\nQuery: {t}" for t in texts
            ]
        else:
            formatted = texts
        embeddings = self.model.encode(
            formatted, normalize_embeddings=True, show_progress_bar=False
        )
        return [e.tolist() for e in embeddings]

    def warm_up(self) -> None:
        """Ensure model is loaded and run a dummy inference."""
        self._ensure_loaded()
        _ = self.embed_query("warm-up")


# ── Rust/Candle Runner ───────────────────────────────────────────────────────


@dataclass
class RustHarrierRunner:
    """Runs our Rust/Candle Harrier implementation via embedding_engine."""

    engine: Any = None  # embedding_engine.EmbeddingEngine, lazy-loaded

    def _ensure_loaded(self) -> None:
        if self.engine is not None:
            return
        import embedding_engine

        self.engine = embedding_engine.EmbeddingEngine(HARRIER_MODEL_ID)

    def embed_query(self, text: str) -> list[float]:
        """Embed a query with the Harrier instruction prefix."""
        self._ensure_loaded()
        formatted = f"Instruct: {QUERY_INSTRUCTION}\nQuery: {text}"
        return self.engine.embed(formatted)

    def embed_document(self, text: str) -> list[float]:
        """Embed a document (no instruction prefix)."""
        self._ensure_loaded()
        return self.engine.embed(text)

    def embed_batch(
        self, texts: list[str], is_query: bool = False
    ) -> list[list[float]]:
        """Embed a batch of texts."""
        self._ensure_loaded()
        if is_query:
            formatted = [
                f"Instruct: {QUERY_INSTRUCTION}\nQuery: {t}" for t in texts
            ]
        else:
            formatted = texts
        return self.engine.embed_batch(formatted)

    def dimensions(self) -> int:
        """Return embedding dimension."""
        self._ensure_loaded()
        return self.engine.dimensions()

    def max_tokens(self) -> int:
        """Return max tokens."""
        self._ensure_loaded()
        return self.engine.max_tokens()

    def warm_up(self) -> None:
        """Ensure model is loaded and run a dummy inference."""
        self._ensure_loaded()
        _ = self.embed_query("warm-up")


# ── Timer utility ────────────────────────────────────────────────────────────


@dataclass
class TimerResult:
    name: str
    elapsed_seconds: float
    extra: dict[str, Any] = None

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


def time_it(name: str, fn, *args, **kwargs) -> tuple[Any, TimerResult]:
    """Time a function call and return (result, TimerResult)."""
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - start
    return result, TimerResult(name=name, elapsed_seconds=elapsed)
