"""
Integration test for embedding_engine with all registered models.

Verifies for each model:
  - Model download from HuggingFace Hub (first use)
  - Single-text embedding produces correct-dimension vector
  - Batch embedding produces correct number of vectors
  - Embeddings are L2-normalized (unit norm ≈ 1.0)
  - Cosine similarity: similar sentences > dissimilar sentences

Models tested:
  - all-MiniLM-L6-v2 (384 dim, BERT, 91 MB)
  - granite-embedding-97m-multilingual-r2 (384 dim, ModernBERT, 186 MB)
  - harrier-oss-v1-270m (640 dim, Gemma3, 545 MB)
"""

import math
import sys
import time
import embedding_engine


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)


# ── Model-specific constants ───────────────────────────────────────────
MODELS = {
    "all-MiniLM-L6-v2": {
        "dims": 384,
        "max_tokens": 256,
        "architecture": "BERT",
    },
    "granite-embedding-97m-multilingual-r2": {
        "dims": 384,
        "max_tokens": 32768,
        "architecture": "ModernBERT",
    },
    "harrier-oss-v1-270m": {
        "dims": 640,
        "max_tokens": 32768,
        "architecture": "Gemma3",
    },
}

SIMILAR_A = "The quick brown fox jumps over the lazy dog."
SIMILAR_B = "A fast brown fox leaped over a sleepy canine."
DISSIMILAR = "Machine learning models require large amounts of training data."


def test_model(model_id: str, expected: dict) -> bool:
    """Run the full integration suite for a single model. Returns True on success."""
    dims = expected["dims"]
    max_tokens = expected["max_tokens"]

    print(f"\n{'─' * 60}")
    print(f"  Model: {model_id}")
    print(f"  Expected: {dims} dims, {max_tokens} max tokens, {expected['architecture']}")
    print(f"{'─' * 60}")

    # 1. Metadata
    info = embedding_engine.EmbeddingEngine.model_info(model_id)
    assert info is not None, f"model_info returned None for {model_id}"
    print(f"  Model info: {info}")

    # 2. Create engine
    engine = embedding_engine.EmbeddingEngine(model_id)
    assert engine.ping() == "embedding_engine ready"
    assert engine.dimensions() == dims, (
        f"Expected {dims} dims, got {engine.dimensions()}"
    )
    assert engine.max_tokens() == max_tokens, (
        f"Expected {max_tokens} tokens, got {engine.max_tokens()}"
    )
    print(f"  Dimensions: {engine.dimensions()}, Max tokens: {engine.max_tokens()}")

    # 3. First embed (triggers model download + load)
    print("  First embed (downloads model if not cached)...")
    t0 = time.time()
    vec = engine.embed("Hello world, this is a test sentence.")
    t1 = time.time()
    print(f"  First embed took {t1 - t0:.1f}s")
    print(f"  Embedding length: {len(vec)}")
    assert len(vec) == dims, f"Expected {dims}, got {len(vec)}"

    # 4. Verify L2 normalization
    norm = math.sqrt(sum(x * x for x in vec))
    print(f"  L2 norm: {norm:.6f} (should be ~1.0)")
    assert abs(norm - 1.0) < 0.01, f"Expected unit norm, got {norm}"

    # 5. Warm embed (model already loaded)
    print("  Warm embed...")
    t0 = time.time()
    _vec2 = engine.embed("The cat sat on the mat.")
    t1 = time.time()
    print(f"  Warm embed took {t1 - t0:.3f}s")

    # 6. Cosine similarity: similar vs dissimilar
    print("  Cosine similarity test...")
    emb_sim_a = engine.embed(SIMILAR_A)
    emb_sim_b = engine.embed(SIMILAR_B)
    emb_dis = engine.embed(DISSIMILAR)

    sim_score = cosine(emb_sim_a, emb_sim_b)
    dis_score = cosine(emb_sim_a, emb_dis)
    print(f"  Similar sentences:    {sim_score:.4f}")
    print(f"  Dissimilar sentences: {dis_score:.4f}")
    print(f"  Delta:                 {sim_score - dis_score:.4f}")

    assert sim_score > dis_score, (
        f"Expected higher cosine similarity for similar sentences "
        f"({sim_score:.4f} vs {dis_score:.4f})"
    )
    assert sim_score > 0.5, (
        f"Expected similar cosine similarity > 0.5, got {sim_score:.4f}"
    )

    # 7. Batch embed
    print("  Batch embed test...")
    texts = ["First sentence.", "Second sentence.", "Third one here."]
    batch = engine.embed_batch(texts)
    assert len(batch) == len(texts), (
        f"Expected {len(texts)} vectors, got {len(batch)}"
    )
    for i, v in enumerate(batch):
        assert len(v) == dims, f"Batch[{i}] has wrong dim: {len(v)}"
        v_norm = math.sqrt(sum(x * x for x in v))
        assert abs(v_norm - 1.0) < 0.01, f"Batch[{i}] norm: {v_norm}"
    print(f"  Batch of {len(texts)} texts: all {len(batch)} vectors valid and normalized")

    print(f"  ✅ {model_id} — PASSED")
    return True


def main() -> None:
    print("=" * 60)
    print("Embedding Engine Integration Test — All Models")
    print("=" * 60)

    # ── Pre-flight: list registered models ───────────────────────────
    models = embedding_engine.EmbeddingEngine.available_models()
    print(f"\nRegistered models: {models}")
    print(f"Count: {len(models)}")

    for expected_id in MODELS:
        assert expected_id in models, (
            f"Model not registered: {expected_id}. Available: {models}"
        )

    # ── Run each model ───────────────────────────────────────────────
    results: dict[str, bool] = {}
    for model_id, expected in MODELS.items():
        try:
            results[model_id] = test_model(model_id, expected)
        except Exception as e:
            print(f"  ❌ {model_id} — FAILED: {e}")
            results[model_id] = False

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("Results Summary")
    print(f"{'=' * 60}")
    all_passed = True
    for model_id, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {model_id}: {status}")
        if not passed:
            all_passed = False

    if not all_passed:
        print("\nSome tests FAILED — see above for details.")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print("All integration tests passed! 🎉")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
