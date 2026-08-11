"""
Comprehensive first-divergence diagnostic for Harrier Rust vs PyTorch.

Exports EVERY intermediate tensor from the official HuggingFace Gemma3
implementation and compares against corresponding Rust/Candle tensors.

Uses identical token IDs to eliminate tokenizer differences.
"""

import math
import json
import sys
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel
from transformers.models.gemma3.modeling_gemma3 import (
    Gemma3TextModel,
    Gemma3RMSNorm,
    Gemma3DecoderLayer,
    Gemma3Attention,
    Gemma3MLP,
    Gemma3RotaryEmbedding,
    apply_rotary_pos_emb,
)
from typing import Optional

# ── Utilities ───────────────────────────────────────────────────────────────

def tensor_fingerprint(name: str, t: torch.Tensor) -> dict:
    """Compute compact tensor fingerprint for comparison."""
    if t is None:
        return {"name": name, "shape": None, "error": "None tensor"}
    x = t.detach().cpu().float()
    flat = x.flatten()
    info = {
        "name": name,
        "shape": list(x.shape),
        "dtype": str(x.dtype).replace("torch.", ""),
        "min": round(x.min().item(), 10),
        "max": round(x.max().item(), 10),
        "mean": round(x.mean().item(), 10),
        "std": round(x.std().item(), 10),
        "l2_norm": round(x.norm().item(), 10),
        "first5": [round(v.item(), 10) for v in flat[:5]],
        "last5": [round(v.item(), 10) for v in flat[-5:]],
    }
    return info


def compare_fingerprints(ref: dict, rust: dict) -> dict:
    """Compare two fingerprints, compute divergence metrics."""
    if ref.get("error") or rust.get("error"):
        return {"status": "SKIP", "reason": ref.get("error") or rust.get("error")}

    if ref["shape"] != rust["shape"]:
        return {"status": "SHAPE_MISMATCH", "ref_shape": ref["shape"], "rust_shape": rust["shape"]}

    ref_flat = [ref["first5"][i] if i < 5 else 0 for i in range(5)]
    rust_flat = [rust["first5"][i] if i < 5 else 0 for i in range(5)]

    max_abs_diff = max(abs(ref["max"] - rust["max"]), abs(ref["min"] - rust["min"]))
    mean_abs_diff = abs(ref["mean"] - rust["mean"])
    l2_diff = abs(ref["l2_norm"] - rust["l2_norm"])

    return {
        "status": "COMPARED",
        "max_abs_diff": round(max_abs_diff, 10),
        "mean_diff": round(mean_abs_diff, 10),
        "l2_diff": round(l2_diff, 10),
        "ref_norm": ref["l2_norm"],
        "rust_norm": rust["l2_norm"],
    }


# ── PyTorch Reference with hooks ────────────────────────────────────────────

def run_pytorch_reference(text: str) -> dict:
    """
    Run the official HuggingFace Gemma3 model and capture ALL intermediate
    tensors via forward hooks.
    """
    model_id = "microsoft/harrier-oss-v1-270m"

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id, torch_dtype=torch.float32)
    model.eval()

    inputs = tokenizer(text, return_tensors="pt")
    input_ids = inputs["input_ids"]
    attention_mask = inputs["attention_mask"]

    print(f"Token IDs: {input_ids[0].tolist()}")
    print(f"Tokens: {tokenizer.convert_ids_to_tokens(input_ids[0].tolist())}")
    print(f"Seq len: {input_ids.shape[1]}")
    print()

    results = {}

    # ── Access model internals ──────────────────────────────────────
    gemma: Gemma3TextModel = model  # AutoModel returns Gemma3TextModel

    embed_tokens = gemma.embed_tokens
    layers = gemma.layers
    final_norm = gemma.norm

    # ── 1. Embedding lookup ────────────────────────────────────────
    with torch.no_grad():
        hidden_states = embed_tokens(input_ids)
        results["embed_tokens"] = tensor_fingerprint("embed_tokens", hidden_states)

        # Normalizer (sqrt(hidden_size))
        normalizer = torch.tensor(gemma.config.hidden_size ** 0.5)
        hidden_states = hidden_states * normalizer
        results["embed_tokens_scaled"] = tensor_fingerprint("embed_tokens_scaled", hidden_states)

        # ── Build causal mask ──────────────────────────────────────
        seq_len = input_ids.shape[1]
        # ALL 18 layers are full_attention, use_bidirectional_attention=False
        # So: causal mask with no sliding window
        causal_mask = torch.triu(
            torch.full((seq_len, seq_len), float("-inf"), dtype=torch.float32),
            diagonal=1,
        )
        # Reshape to (1, 1, seq_len, seq_len) for broadcasting
        causal_mask = causal_mask.unsqueeze(0).unsqueeze(0)
        results["causal_mask"] = tensor_fingerprint("causal_mask", causal_mask)

        # ── Position IDs ───────────────────────────────────────────
        position_ids = torch.arange(seq_len, dtype=torch.long).unsqueeze(0)
        results["position_ids"] = tensor_fingerprint("position_ids", position_ids.float())

        # ── 2. Process each layer (with hooks) ─────────────────────
        for layer_idx, layer in enumerate(layers):
            layer: Gemma3DecoderLayer = layer
            prefix = f"layer_{layer_idx}"

            # input_layernorm
            residual = hidden_states
            normed = layer.input_layernorm(hidden_states)
            results[f"{prefix}_input_layernorm"] = tensor_fingerprint(f"{prefix}_input_layernorm", normed)

            # self_attn
            attn: Gemma3Attention = layer.self_attn
            bsz, q_len, _ = normed.shape

            # Q, K, V projections
            query_states = attn.q_proj(normed)
            key_states = attn.k_proj(normed)
            value_states = attn.v_proj(normed)

            query_states = query_states.view(bsz, q_len, attn.config.num_attention_heads, attn.head_dim)
            key_states = key_states.view(bsz, q_len, attn.config.num_key_value_heads, attn.head_dim)
            value_states = value_states.view(bsz, q_len, attn.config.num_key_value_heads, attn.head_dim)

            results[f"{prefix}_Q_proj"] = tensor_fingerprint(f"{prefix}_Q_proj", query_states)
            results[f"{prefix}_K_proj"] = tensor_fingerprint(f"{prefix}_K_proj", key_states)
            results[f"{prefix}_V_proj"] = tensor_fingerprint(f"{prefix}_V_proj", value_states)

            # Q/K RMS norm
            query_states = attn.q_norm(query_states)
            key_states = attn.k_norm(key_states)
            results[f"{prefix}_Q_norm"] = tensor_fingerprint(f"{prefix}_Q_norm", query_states)
            results[f"{prefix}_K_norm"] = tensor_fingerprint(f"{prefix}_K_norm", key_states)

            # Transpose to (b, heads, seq, head_dim)
            query_states = query_states.transpose(1, 2)
            key_states = key_states.transpose(1, 2)
            value_states = value_states.transpose(1, 2)

            results[f"{prefix}_Q_ready"] = tensor_fingerprint(f"{prefix}_Q_ready", query_states)
            results[f"{prefix}_K_ready"] = tensor_fingerprint(f"{prefix}_K_ready", key_states)
            results[f"{prefix}_V_ready"] = tensor_fingerprint(f"{prefix}_V_ready", value_states)

            # RoPE — rotary_emb is on the model, not the attention layer
            cos, sin = gemma.rotary_emb(value_states, position_ids, "full_attention")
            query_states, key_states = apply_rotary_pos_emb(query_states, key_states, cos, sin)
            results[f"{prefix}_Q_rope"] = tensor_fingerprint(f"{prefix}_Q_rope", query_states)
            results[f"{prefix}_K_rope"] = tensor_fingerprint(f"{prefix}_K_rope", key_states)

            # query_pre_attn_scalar — stored as attn.scaling = config.query_pre_attn_scalar**-0.5
            # The scaling is applied to QK^T in eager_attention_forward, not to Q directly.
            # We skip pre-scaling Q here since HF doesn't do it.

            # GQA repeat KV
            n_repeats = attn.num_key_value_groups
            if n_repeats > 1:
                key_states = key_states.repeat_interleave(n_repeats, dim=1)
                value_states = value_states.repeat_interleave(n_repeats, dim=1)

            # Attention — use attn.scaling (= query_pre_attn_scalar**-0.5)
            attn_weights = torch.matmul(query_states, key_states.transpose(2, 3)) * attn.scaling
            results[f"{prefix}_attn_logits"] = tensor_fingerprint(f"{prefix}_attn_logits", attn_weights)

            # Apply mask
            attn_weights = attn_weights + causal_mask
            results[f"{prefix}_attn_masked"] = tensor_fingerprint(f"{prefix}_attn_masked", attn_weights)

            # Softmax
            attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(query_states.dtype)
            results[f"{prefix}_attn_probs"] = tensor_fingerprint(f"{prefix}_attn_probs", attn_weights)

            # Attention output
            attn_output = torch.matmul(attn_weights, value_states)
            results[f"{prefix}_attn_output"] = tensor_fingerprint(f"{prefix}_attn_output", attn_output)

            # Reshape + output projection
            attn_output = attn_output.transpose(1, 2).contiguous()
            attn_output = attn_output.reshape(bsz, q_len, -1)
            attn_output = attn.o_proj(attn_output)
            results[f"{prefix}_attn_o_proj"] = tensor_fingerprint(f"{prefix}_attn_o_proj", attn_output)

            # Post-attention norm + residual
            post_attn = layer.post_attention_layernorm(attn_output)
            results[f"{prefix}_post_attn_norm"] = tensor_fingerprint(f"{prefix}_post_attn_norm", post_attn)
            hidden_states = residual + post_attn
            results[f"{prefix}_post_attn_residual"] = tensor_fingerprint(f"{prefix}_post_attn_residual", hidden_states)

            # MLP
            residual = hidden_states
            pre_ffn = layer.pre_feedforward_layernorm(hidden_states)
            results[f"{prefix}_pre_ffn_norm"] = tensor_fingerprint(f"{prefix}_pre_ffn_norm", pre_ffn)

            mlp: Gemma3MLP = layer.mlp
            gate = mlp.gate_proj(pre_ffn)
            up = mlp.up_proj(pre_ffn)
            results[f"{prefix}_mlp_gate"] = tensor_fingerprint(f"{prefix}_mlp_gate", gate)
            results[f"{prefix}_mlp_up"] = tensor_fingerprint(f"{prefix}_mlp_up", up)

            # Activation: gelu_pytorch_tanh
            activated = F.gelu(gate, approximate="tanh")
            results[f"{prefix}_mlp_activation"] = tensor_fingerprint(f"{prefix}_mlp_activation", activated)

            mlp_intermediate = activated * up
            results[f"{prefix}_mlp_intermediate"] = tensor_fingerprint(f"{prefix}_mlp_intermediate", mlp_intermediate)

            mlp_output = mlp.down_proj(mlp_intermediate)
            results[f"{prefix}_mlp_output"] = tensor_fingerprint(f"{prefix}_mlp_output", mlp_output)

            # Post-FFN norm + residual
            post_ffn = layer.post_feedforward_layernorm(mlp_output)
            results[f"{prefix}_post_ffn_norm"] = tensor_fingerprint(f"{prefix}_post_ffn_norm", post_ffn)
            hidden_states = residual + post_ffn
            results[f"{prefix}_layer_output"] = tensor_fingerprint(f"{prefix}_layer_output", hidden_states)

        # ── 3. Final norm ──────────────────────────────────────────
        final = final_norm(hidden_states)
        results["final_norm"] = tensor_fingerprint("final_norm", final)

        # ── 4. Last-token pool ─────────────────────────────────────
        # Use attention_mask to find last non-padding token
        seq_lens = attention_mask.sum(dim=1) - 1
        last_hidden = final[0, seq_lens[0], :]
        results["last_token_pool"] = tensor_fingerprint("last_token_pool", last_hidden)

        # ── 5. L2 normalize ────────────────────────────────────────
        normalized = F.normalize(last_hidden, p=2, dim=-1)
        results["l2_normalized"] = tensor_fingerprint("l2_normalized", normalized)

    return results


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    text = "Hello world"

    print("=" * 70)
    print("Harrier PyTorch Reference — Complete Tensor Export")
    print("=" * 70)
    print()

    results = run_pytorch_reference(text)

    print()
    print("=" * 70)
    print("FULL TENSOR FINGERPRINTS (JSON)")
    print("=" * 70)

    # Print as JSON for easy comparison
    output = {}
    for name, info in results.items():
        output[name] = info
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
