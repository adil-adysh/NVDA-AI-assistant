"""
Harrier reference vs Rust/Candle comparison script.

Runs the same inputs through:
  1. Official HuggingFace model (sentence-transformers)
  2. Our Rust/Candle implementation

Prints full-precision comparison metrics.
"""

import math
import sys
import embedding_engine


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)


def l2_dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def compare(name: str, ref: list[float], rust: list[float]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")

    assert len(ref) == len(rust), f"Dimension mismatch: {len(ref)} vs {len(rust)}"

    max_abs_diff = max(abs(a - b) for a, b in zip(ref, rust))
    mean_abs_diff = sum(abs(a - b) for a, b in zip(ref, rust)) / len(ref)
    cos = cosine(ref, rust)
    l2 = l2_dist(ref, rust)
    ref_norm = math.sqrt(sum(x * x for x in ref))
    rust_norm = math.sqrt(sum(x * x for x in rust))
    ref_minmax = (min(ref), max(ref))
    rust_minmax = (min(rust), max(rust))

    print(f"  Reference norm:       {ref_norm:.10f}")
    print(f"  Rust norm:            {rust_norm:.10f}")
    print(f"  Cosine(reference,rust): {cos:.10f}")
    print(f"  Max abs difference:   {max_abs_diff:.10f}")
    print(f"  Mean abs difference:  {mean_abs_diff:.10f}")
    print(f"  L2 difference:        {l2:.10f}")
    print(f"  Reference min/max:    {ref_minmax[0]:.10f} / {ref_minmax[1]:.10f}")
    print(f"  Rust min/max:         {rust_minmax[0]:.10f} / {rust_minmax[1]:.10f}")

    # Print first 5 values of each
    print(f"  Reference[:5]: {[round(v, 8) for v in ref[:5]]}")
    print(f"  Rust[:5]:      {[round(v, 8) for v in rust[:5]]}")


def get_reference_embeddings(texts: list[str], instruction: str | None = None) -> list[list[float]]:
    """Get reference embeddings from the official Harrier model via sentence-transformers."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        "microsoft/harrier-oss-v1-270m",
        model_kwargs={"dtype": "auto"},
        device="cpu",
    )

    if instruction:
        formatted = [f"Instruct: {instruction}\nQuery: {t}" for t in texts]
    else:
        formatted = texts

    embeddings = model.encode(formatted, normalize_embeddings=True)
    return [e.tolist() for e in embeddings]


def get_rust_embeddings(texts: list[str], model_id: str, instruction: str | None = None) -> list[list[float]]:
    """Get embeddings from our Rust/Candle implementation.

    Applies the official Harrier instruction prefix format for queries.
    Documents use raw text (no prefix).
    """
    engine = embedding_engine.EmbeddingEngine(model_id)
    if instruction:
        formatted = [f"Instruct: {instruction}\nQuery: {t}" for t in texts]
    else:
        formatted = texts
    return engine.embed_batch(formatted)


def main() -> None:
    print("=" * 60)
    print("Harrier Reference vs Rust Comparison")
    print("=" * 60)

    # Test inputs
    short_text = "Hello world, this is a test sentence."
    short_similar = "A greeting to the world with a sample phrase."

    # Instruction format (matching the official one)
    web_search_instruction = "Given a web search query, retrieve relevant passages that answer the query"

    # ── Test 1: Short query text (WITH instruction) ──────────────
    print("\n\n### Phase 1: Getting reference embeddings from official model...")
    ref_short = get_reference_embeddings([short_text], instruction=web_search_instruction)
    print(f"  Got {len(ref_short[0])}-dim reference embedding")

    rust_short = get_rust_embeddings([short_text], "harrier-oss-v1-270m", instruction=web_search_instruction)
    print(f"  Got {len(rust_short[0])}-dim Rust embedding")

    compare("Short query (with instruction)", ref_short[0], rust_short[0])

    # ── Test 2: Short document (NO instruction) ──────────────
    ref_doc = get_reference_embeddings([short_text], instruction=None)
    rust_doc = get_rust_embeddings([short_text], "harrier-oss-v1-270m", instruction=None)
    compare("Short document (no instruction)", ref_doc[0], rust_doc[0])

    # ── Test 3: Cosine similarity between two similar texts ────
    ref_sim_a = get_reference_embeddings([short_text], instruction=web_search_instruction)
    ref_sim_b = get_reference_embeddings([short_similar], instruction=web_search_instruction)
    rust_sim_a = get_rust_embeddings([short_text], "harrier-oss-v1-270m", instruction=web_search_instruction)
    rust_sim_b = get_rust_embeddings([short_similar], "harrier-oss-v1-270m", instruction=web_search_instruction)

    ref_cos = cosine(ref_sim_a[0], ref_sim_b[0])
    rust_cos = cosine(rust_sim_a[0], rust_sim_b[0])
    print(f"\n{'=' * 60}")
    print(f"  Cosine similarity (similar pair)")
    print(f"{'=' * 60}")
    print(f"  Reference cosine: {ref_cos:.10f}")
    print(f"  Rust cosine:      {rust_cos:.10f}")


if __name__ == "__main__":
    main()
