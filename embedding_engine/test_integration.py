"""
Integration test for embedding_engine with the real all-MiniLM-L6-v2 model.

Verifies:
  - Model download from HuggingFace Hub (first use, ~91 MB)
  - Single-text embedding produces correct-dimension vector
  - Batch embedding produces correct number of vectors
  - Embeddings are L2-normalized (unit norm ≈ 1.0)
  - Cosine similarity: similar sentences > dissimilar sentences
"""

import math
import time
import embedding_engine


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)


def main() -> None:
    print("=" * 60)
    print("Embedding Engine Integration Test")
    print("=" * 60)

    # 1. Metadata
    print("\n--- Model Metadata ---")
    models = embedding_engine.EmbeddingEngine.available_models()
    assert "all-MiniLM-L6-v2" in models, f"Model not registered: {models}"
    print(f"Available models: {models}")

    info = embedding_engine.EmbeddingEngine.model_info("all-MiniLM-L6-v2")
    assert info is not None
    print(f"Model info: {info}")

    # 2. Create engine
    print("\n--- Engine Creation ---")
    engine = embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")
    assert engine.ping() == "embedding_engine ready"
    assert engine.dimensions() == 384, f"Expected 384 dims, got {engine.dimensions()}"
    assert engine.max_tokens() == 256, f"Expected 256 tokens, got {engine.max_tokens()}"
    print(f"Dimensions: {engine.dimensions()}, Max tokens: {engine.max_tokens()}")

    # 3. First embed (triggers model download + load)
    print("\n--- First Embed (downloads model if not cached) ---")
    t0 = time.time()
    vec = engine.embed("Hello world, this is a test sentence.")
    t1 = time.time()
    print(f"First embed took {t1 - t0:.1f}s")
    print(f"Embedding length: {len(vec)}")
    assert len(vec) == 384, f"Expected 384, got {len(vec)}"

    # 4. Verify L2 normalization
    norm = math.sqrt(sum(x * x for x in vec))
    print(f"L2 norm: {norm:.6f} (should be ~1.0)")
    assert abs(norm - 1.0) < 0.01, f"Expected unit norm, got {norm}"

    # 5. Warm embed (model already loaded)
    print("\n--- Warm Embed ---")
    t0 = time.time()
    vec2 = engine.embed("The cat sat on the mat.")
    t1 = time.time()
    print(f"Warm embed took {t1 - t0:.3f}s")

    # 6. Cosine similarity: similar vs dissimilar
    print("\n--- Cosine Similarity ---")
    similar_a = "The quick brown fox jumps over the lazy dog."
    similar_b = "A fast brown fox leaped over a sleepy canine."
    dissimilar = "Machine learning models require large amounts of training data."

    emb_sim_a = engine.embed(similar_a)
    emb_sim_b = engine.embed(similar_b)
    emb_dis = engine.embed(dissimilar)

    sim_score = cosine(emb_sim_a, emb_sim_b)
    dis_score = cosine(emb_sim_a, emb_dis)
    print(f"Similar sentences:    {sim_score:.4f}")
    print(f"Dissimilar sentences: {dis_score:.4f}")
    print(f"Delta:                 {sim_score - dis_score:.4f}")

    assert sim_score > dis_score, (
        f"Expected similar sentences to have higher cosine similarity "
        f"than dissimilar ({sim_score:.4f} vs {dis_score:.4f})"
    )
    assert sim_score > 0.5, (
        f"Expected similar sentences to have cosine similarity > 0.5, got {sim_score:.4f}"
    )

    # 7. Batch embed
    print("\n--- Batch Embed ---")
    texts = ["First sentence.", "Second sentence.", "Third one here."]
    batch = engine.embed_batch(texts)
    assert len(batch) == len(texts), f"Expected {len(texts)} vectors, got {len(batch)}"
    for i, v in enumerate(batch):
        assert len(v) == 384, f"Batch[{i}] has wrong dim: {len(v)}"
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 0.01, f"Batch[{i}] norm: {norm}"
    print(f"Batch of {len(texts)} texts: all {len(batch)} vectors valid and normalized")

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
