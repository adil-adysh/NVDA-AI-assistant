"""
Layer-by-layer diagnostic comparing PyTorch reference vs Rust/Candle Harrier.
"""

import math
import sys
import torch
import embedding_engine
from transformers import AutoTokenizer, AutoModel
from sentence_transformers import SentenceTransformer


def compare_tensor(name: str, ref: torch.Tensor, rust_values: list[float], rust_shape: tuple) -> None:
    """Compare a PyTorch tensor with Rust values."""
    ref_flat = ref.detach().cpu().float().flatten().tolist()
    assert len(ref_flat) == len(rust_values), (
        f"{name}: shape mismatch ref={ref.shape} rust={rust_shape}, "
        f"len(ref)={len(ref_flat)}, len(rust)={len(rust_values)}"
    )

    max_diff = max(abs(a - b) for a, b in zip(ref_flat, rust_values))
    mean_diff = sum(abs(a - b) for a, b in zip(ref_flat, rust_values)) / len(ref_flat)
    cos = sum(a * b for a, b in zip(ref_flat, rust_values)) / (
        math.sqrt(sum(a * a for a in ref_flat)) * math.sqrt(sum(b * b for b in rust_values))
    )
    print(f"  {name}: max_diff={max_diff:.8e}, mean_diff={mean_diff:.8e}, cos={cos:.10f}")
    if max_diff > 1e-4:
        print(f"    ref[:3]={[round(v, 8) for v in ref_flat[:3]]}")
        print(f"    rust[:3]={[round(v, 8) for v in rust_values[:3]]}")


def main():
    text = "Hello world, this is a test."

    # ── Reference (PyTorch) ───────────────────────────────────
    tokenizer = AutoTokenizer.from_pretrained("microsoft/harrier-oss-v1-270m")
    model = AutoModel.from_pretrained("microsoft/harrier-oss-v1-270m", torch_dtype=torch.float32)
    model.eval()

    inputs = tokenizer(text, return_tensors="pt")
    print(f"Token IDs: {inputs['input_ids'][0].tolist()}")
    print(f"Tokens: {tokenizer.convert_ids_to_tokens(inputs['input_ids'][0].tolist())}")
    print(f"Attention mask: {inputs['attention_mask'][0].tolist()}")
    print()

    with torch.no_grad():
        outputs = model(**inputs, output_hidden_states=True)
        ref_hidden = outputs.last_hidden_state  # (1, seq_len, 640)

        # Apply final norm + pooling + normalize (matching our pipeline)
        ref_pooled = ref_hidden[0, -1, :]  # last token
        ref_pooled = torch.nn.functional.normalize(ref_pooled, p=2, dim=0)

    # ── Rust/Candle ────────────────────────────────────────────
    engine = embedding_engine.EmbeddingEngine("harrier-oss-v1-270m")
    rust_embedding = engine.embed(text)

    # ── Compare ───────────────────────────────────────────────
    print("=" * 60)
    print("Final embedding comparison")
    print("=" * 60)
    compare_tensor("last_hidden(output_normed)", ref_pooled, rust_embedding, (1, 640))

    # Get input ids tokens
    print()
    print("=" * 60)
    print("Reference hidden states after each layer")
    print("=" * 60)
    for i, h in enumerate(outputs.hidden_states):
        if h is not None:
            print(f"  Layer {i}: shape={h.shape}, norm={h.norm():.4f}, "
                  f"min={h.min():.4f}, max={h.max():.4f}")


if __name__ == "__main__":
    main()
