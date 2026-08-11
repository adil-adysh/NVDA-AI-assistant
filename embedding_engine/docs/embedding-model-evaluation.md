# Embedding Model Evaluation Report

> **Date:** 2026-08-11  
> **Context:** Evaluating replacement candidates for `sentence-transformers/all-MiniLM-L6-v2` (current default) in the NVDA AI Assistant embedding engine.  
> **Key requirements:** multilingual (Hindi, Urdu, Gujarati), CPU-first, small download size, Rust/Candle compatibility.

---

## Table of Contents

1. [Candidates Overview](#1-candidates-overview)
2. [Full Property Matrix](#2-full-property-matrix)
3. [Architecture Deep-Dive](#3-architecture-deep-dive)
4. [Language Coverage](#4-language-coverage)
5. [Quality Benchmarks](#5-quality-benchmarks)
6. [Download Sizes](#6-download-sizes)
7. [Pooling Strategy Comparison](#7-pooling-strategy-comparison)
8. [Candle Integration Feasibility](#8-candle-integration-feasibility)
9. [Recommendation & Action Plan](#9-recommendation--action-plan)
10. [Appendix: Raw Model Card Data](#10-appendix-raw-model-card-data)

---

## 1. Candidates Overview

Five models were evaluated using `hf models info` and `hf models ls -R`:

| # | Model ID | Developer | Type |
|---|---|---|---|
| 1 | `ibm-granite/granite-embedding-97m-multilingual-r2` | IBM | Encoder (ModernBERT) |
| 2 | `microsoft/bitnet-embedding-270m` | Microsoft | Decoder (Gemma3, 1.58-bit) |
| 3 | `microsoft/harrier-oss-v1-270m` | Microsoft | Decoder (Gemma3, BF16) |
| 4 | `Qwen/Qwen3-Embedding-0.6B` | Alibaba (Qwen) | Decoder (Qwen3) |
| 5 | `microsoft/Multilingual-MiniLM-L12-H384` | Microsoft | Encoder (BERT) |

Model #5 is the multilingual variant of the current MiniLM family (baseline reference — not recommended).

---

## 2. Full Property Matrix

| Property | Granite 97M R2 | BitNet 270M | Harrier 270M | Qwen3 0.6B | MiniLM L12 |
|---|---|---|---|---|---|
| **HF ID** | `ibm-granite/granite-embedding-97m-multilingual-r2` | `microsoft/bitnet-embedding-270m` | `microsoft/harrier-oss-v1-270m` | `Qwen/Qwen3-Embedding-0.6B` | `microsoft/Multilingual-MiniLM-L12-H384` |
| **Parameters** | **97M** | 270M | 270M | 595M | ~117M (21M tx + 96M emb) |
| **Weight file size** | **185.9 MB** | 350.5 MB | 511.4 MB | 1,136.4 MB | 448.9 MB |
| **Embedding dimension** | 384 | 640 | 640 | 1,024 (32–1,024 MRL) | 384 |
| **Max tokens (context)** | 32,768 | 32,768 | 32,768 | 32,768 | 128–512 |
| **Architecture** | Encoder (ModernBERT) | Decoder (Gemma3) | Decoder (Gemma3) | Decoder (Qwen3) | Encoder (BERT) |
| **Layers** | 12 | 18 | 18 | 28 | 12 |
| **Attention heads** | 12 (12 KV) | 4 (1 KV) | 4 (1 KV) | 16 (8 KV) | 12 |
| **Hidden size** | 384 | 640 | 640 | 1,024 | 384 |
| **Intermediate size** | 1,536 | 2,048 | 2,048 | 3,072 | 1,536 |
| **Activation** | SiLU | GELU | gelu_pytorch_tanh | SiLU | GELU |
| **Position encoding** | Absolute + RoPE (dual θ) | RoPE | RoPE (θ=1,000,000) | RoPE (θ=1,000,000) | Absolute |
| **Norm type** | LayerNorm | SubLN + RMS | RMSNorm | RMSNorm | LayerNorm |
| **Vocab size** | 180,000 | 262,144 | 262,144 | 151,669 | 250,000 |
| **Tokenizer** | Custom ModernBERT | Gemma (262K) | Gemma (262K) | Qwen3 (151K) | XLM-R (sentencepiece) |
| **Tied embeddings** | No | No | No | Yes | No |
| **Pooling** | CLS → L2 | Last-token (EOS) → L2 | Last-token (EOS) → L2 | Last-token (EOS) → L2 | Masked mean → L2 |
| **Instruction prefix** | ❌ None | Recommended | **Required** | Recommended | ❌ None |
| **MRL (variable dim)** | ❌ | ❌ | ❌ | ✅ 32–1,024 | ❌ |
| **Weight format** | BF16 safetensors | GGUF (1.58-bit ternary) | BF16 safetensors | BF16 safetensors | PyTorch bin |
| **ONNX / OpenVINO** | ✅ Both + INT8 | ❌ | ❌ | ❌ | ❌ |
| **MTEB v2 Mean** | 52.2 (subset avg) | **66.26** | **66.5** | ~65 (est.) | — |
| **ML Retrieval** | 60.3 | — | — | — | — |
| **Code Retrieval** | 60.4 | — | — | — | — |
| **Languages (HF tags)** | 52 enhanced | 93 | 93 | 100+ claimed | 16 |
| **Gujarati (gu)** | ❌ Not in enhanced | ✅ | ✅ | ✅ *(via base model)* | ❌ |
| **Hindi (hi)** | ✅ Enhanced | ✅ | ✅ | ✅ | ✅ |
| **Urdu (ur)** | ✅ Enhanced | ✅ | ✅ | ✅ | ✅ |
| **License** | Apache 2.0 | MIT | MIT | Apache 2.0 | MIT |
| **Release date** | Apr 2026 | Jul 2026 | Mar 2026 | Jun 2025 | Jun 2020 |
| **HF downloads** | 180,510 | 777 | 473,627 | **8,119,003** | 51,460 |
| **HF likes** | 133 | 15 | 192 | **1,141** | 107 |
| **Candle feasibility** | ⚠️ ModernBERT unknown | ❌ BitLinear unsupported | ⚠️ Gemma3 unknown | ⚠️ Qwen3 unknown | ✅ BertModel working |

---

## 3. Architecture Deep-Dive

### 3.1 Granite 97M R2 — Encoder (ModernBERT)

```
config.json → ModernBertModel
hidden_size: 384, intermediate_size: 1536
num_hidden_layers: 12, num_attention_heads: 12
hidden_activation: silu
local_attention: 128, global_attn_every_n_layers: 3
global_rope_theta: 150000, local_rope_theta: 160000
vocab_size: 180000
```

- **Derivation:** Pruned from `granite-embedding-311m-multilingual-r2` (22→12 layers, 262K→180K vocab)
- **Training:** Knowledge distillation from multiple teachers + contrastive fine-tuning
- **Key features:** Alternating global/local attention every 3 layers, dual RoPE frequencies, SiLU activations
- **Pooling:** CLS token at position 0, then L2 normalization — **simplest pooling of all candidates**
- **Deployment:** Ships ONNX, OpenVINO, and INT8 quantized variants for CPU inference
- **Paper:** [Granite Embedding Multilingual R2 Models](https://huggingface.co/papers/2605.13521)

### 3.2 BitNet 270M — Decoder (Gemma3, 1.58-bit)

```
No config.json in repo (GGUF-only release)
Backbone: Gemma3
hidden_size: 640, intermediate_size: 2048
num_hidden_layers: 18, num_attention_heads: 4, num_key_value_heads: 1
head_dim: 256
activation: GELU
vocab_size: 262,144 (Gemma tokenizer)
```

- **Quantization:** Native 1.58-bit ternary weights (−1, 0, +1) with 8-bit activations (W1.58A8)
- **Weight quantization:** absmean quantization to ternary
- **Activation quantization:** absmax quantization per-token
- **Training pipeline:**
  1. Convert backbone to BitNet-style encoder (BitLinear layers, SubLN norm)
  2. Continual contrastive pre-training on 1B text pairs (InfoNCE loss)
  3. Distillation-based SFT from FP16 teacher (Harrier)
- **Format:** **GGUF only** — no safetensors, no PyTorch weights
- **CPU inference:** Requires `bitnet.cpp` — not compatible with Candle natively
- **Paper:** [BitNet Text Embeddings](https://arxiv.org/abs/2606.25674)
- **Note:** Achieves 99.6% of Harrier's MTEB score (66.26 vs 66.5) at 1.58-bit

### 3.3 Harrier 270M — Decoder (Gemma3, BF16)

```
config.json → Gemma3TextModel
hidden_size: 640, intermediate_size: 2048
num_hidden_layers: 18, num_attention_heads: 4, num_key_value_heads: 1
head_dim: 256
hidden_activation: gelu_pytorch_tanh
max_position_embeddings: 32768
rope_theta: 1000000, sliding_window: 512
use_bidirectional_attention: false (causal decoder)
vocab_size: 262144
```

- **Architecture:** Decoder-only with causal (unidirectional) attention and sliding window
- **Pooling:** Last non-padding token → L2 normalize
- **Instruction requirement:** Queries MUST use format `"Instruct: {task_description}\nQuery: {query}"`
- **Documents:** No instruction prefix needed
- **Training:** Contrastive learning + knowledge distillation from larger models
- **MTEB v2:** 66.5 (state-of-the-art for 270M class at release)

### 3.4 Qwen3 0.6B — Decoder (Qwen3)

```
config.json → Qwen3ForCausalLM
hidden_size: 1024, intermediate_size: 3072
num_hidden_layers: 28, num_attention_heads: 16, num_key_value_heads: 8
head_dim: 128
hidden_act: silu
max_position_embeddings: 32768
rope_theta: 1000000
tie_word_embeddings: true
vocab_size: 151669
```

- **Base model:** `Qwen/Qwen3-0.6B-Base` (general-purpose LM, fine-tuned for embeddings)
- **MRL (Matryoshka Representation Learning):** Single model produces valid embeddings at any dimension 32–1,024
  - Enables shrinking vector stores without re-encoding
  - Can match current 384-dim setup with no architectural changes
- **Instruction-aware:** Recommended format `"Instruct: {task_description}\nQuery: {query}"`
  - 1–5% quality drop without instructions per model card
- **Training:** Contrastive fine-tuning + distillation from larger Qwen3 embedding models
- **Family:** 0.6B / 4B / 8B — the 8B model is #1 on MTEB multilingual leaderboard (70.58)
- **Paper:** [Qwen3 Embedding Blog](https://qwenlm.github.io/blog/qwen3-embedding/)

### 3.5 MiniLM L12 — Encoder (BERT)

```
config.json → BertModel
hidden_size: 384, intermediate_size: 1536
num_hidden_layers: 12, num_attention_heads: 12
vocab_size: 250,000 (XLM-R tokenizer from sentencepiece)
```

- **Architecture:** Standard BERT encoder (same as current MiniLM L6 but 12 layers)
- **Weird quirk:** Uses `BertModel` with `XLMRobertaTokenizer` — `AutoTokenizer` breaks
- **Pooling:** Masked mean pooling (same as current implementation)
- **Training:** Task-agnostic distillation (not purpose-built for embeddings)
- **Released:** June 2020 — oldest candidate, no MTEB scores on model card
- **Note:** 21M transformer params + 96M embedding params (the embedding layer dominates size)

---

## 4. Language Coverage

### 4.1 Target Language Matrix

| ISO | Language | Granite 97M | BitNet 270M | Harrier 270M | Qwen3 0.6B | MiniLM L12 |
|---|---|---|---|---|---|---|
| **hi** | Hindi | ✅ Enhanced | ✅ Tagged | ✅ Tagged | ✅ *(claimed)* | ✅ |
| **ur** | Urdu | ✅ Enhanced | ✅ Tagged | ✅ Tagged | ✅ *(claimed)* | ✅ |
| **gu** | Gujarati | ❌ | ✅ Tagged | ✅ Tagged | ✅ *(claimed)* | ❌ |
| pa | Punjabi | ❌ | ✅ | ✅ | ? | ❌ |
| bn | Bengali | ✅ Enhanced | ✅ | ✅ | ? | ❌ |
| mr | Marathi | ✅ Enhanced | ✅ | ✅ | ? | ❌ |
| te | Telugu | ✅ Enhanced | ✅ | ✅ | ? | ❌ |
| ta | Tamil | ❌ | ✅ | ✅ | ? | ❌ |
| ml | Malayalam | ❌ | ✅ | ✅ | ? | ❌ |
| kn | Kannada | ❌ | ✅ | ✅ | ? | ❌ |
| ne | Nepali | ❌ | ✅ | ✅ | ? | ❌ |
| si | Sinhala | ❌ | ✅ | ✅ | ? | ❌ |

### 4.2 Complete Language Tag Breakdown

#### Granite 97M R2 — 52 enhanced languages
```
ar az bg bn ca cs da de el en es et fa fi fr he hi hr hu id is
it ja ka kk km ko lt lv mr ms nl no pl pt ro ru sk sl sq sr sv
sw te th tl tr uk ur uz vi zh
```
Plus 200+ from pretraining (not explicitly listed).

#### BitNet 270M & Harrier 270M — 93 languages each (identical sets)
```
af am ar as az be bg bn br bs ca cs cy da de el en eo es et eu
fa fi fr fy ga gd gl gu ha he hi hr hu hy id is it ja jv ka kk
km kn ko ku ky la lo lt lv mg mk ml mn mr ms my ne nl no om or
pa pl ps pt ro ru sa sd si sk sl so sq sr su sv sw ta te th tl
tr ug uk ur uz vi xh yi zh
```
Both derived from Gemma3 backbone. Includes Gujarati (`gu`).

#### Qwen3 0.6B — 100+ languages (claimed, no explicit tags)
No individual language tags in HF metadata. The base model `Qwen3-0.6B-Base` supports 119 languages including Gujarati, Hindi, and Urdu.

#### MiniLM L12 — 16 languages
```
en ar bg de el es fr hi ru sw th tr ur vi zh
```
Very narrow. No Gujarati, no Bengali, no Tamil, etc.

### 4.3 Key Takeaway

- **Granite** has the strongest explicit quality guarantee for Hindi and Urdu but **omits Gujarati** from enhanced training
- **BitNet/Harrier** have explicit Gujarati tags — if Gujarati is required, these are the safest bets
- **Qwen3** likely works for Gujarati via base model pretraining but has no explicit quality guarantees
- **MiniLM** is unsuitable for any South Asian use beyond Hindi/Urdu

---

## 5. Quality Benchmarks

### 5.1 Available MTEB Scores

| Model | MTEB v2 Mean | Bitext | Classification | Clustering | Pair Class. | Reranking | Retrieval | STS |
|---|---|---|---|---|---|---|---|---|
| **Granite 97M** | 52.2 *(task avg)* | — | — | — | — | — | 60.3 (ML) | — |
| **BitNet 270M** | 66.26 | 80.47 | 71.09 | 52.37 | 79.72 | 60.50 | 66.71 | 74.35 |
| **Harrier 270M** | **66.5** | — | — | — | — | — | — | — |
| **Qwen3 0.6B** | ~65 *(est.)* | — | — | — | — | — | — | — |
| **MiniLM L12** | — | — | — | — | — | — | — | — |

### 5.2 Granite Task-Group Breakdown
Granite reports per-category averages, not an overall MTEB v2 mean (different methodology):

| Benchmark | Granite 97M R2 | Granite 311M R2 (full) |
|---|---|---|
| MTEB Multilingual Retrieval (18 tasks) | 60.3 | 65.2 |
| MTEB English Retrieval (10 tasks) | 50.1 | 52.6 |
| MTEB Code Retrieval (12 tasks) | 60.4 | 63.8 |
| LongEmbed (6 tasks) | 65.5 | 71.7 |
| RaR-b Reasoning (17 tasks) | 24.9 | 28.0 |
| **Throughput (docs/s, H100)** | **2,534** | 1,828 |

Key comparison: Granite 97M R2 (52.2 avg) achieved a **+14.6 point gain** over its predecessor `granite-embedding-107m-multilingual` (37.6 avg).

### 5.3 BitNet vs Harrier
BitNet (66.26) achieves **99.6%** of Harrier's MTEB v2 score (66.5) while using 1.58-bit ternary weights instead of BF16 — remarkable for the compression ratio.

### 5.4 Important Caveats

- **Granite scores are NOT directly comparable** to Harrier/BitNet MTEB v2 means — different task subsets and averaging methodology
- **Qwen3 0.6B score is estimated** — the 8B model scores 70.58 (#1 leaderboard); the 0.6B likely scores around 65 based on scaling trends
- **MiniLM L12 has no MTEB scores** — only XNLI (71.1 avg) and MLQA (63.2 F1) fine-tuning benchmarks

---

## 6. Download Sizes

### 6.1 Weight File Sizes (what you actually download for inference)

| Model | File | Size | Format |
|---|---|---|---|
| **Granite 97M** | `model.safetensors` | **185.9 MB** | BF16 |
| **BitNet 270M** | `bitnet-embeddings-270m-bf16-i2_s.gguf` | 350.5 MB | GGUF (1.58-bit) |
| **Harrier 270M** | `model.safetensors` | 511.4 MB | BF16 |
| **Qwen3 0.6B** | `model.safetensors` | 1,136.4 MB | BF16 |
| **MiniLM L12** | `pytorch_model.bin` | 448.9 MB | FP32 |
| *Current* | `model.safetensors` (all-MiniLM-L6-v2) | ~91 MB | FP16 |

### 6.2 Total Repository Sizes

| Model | Total repo | Components |
|---|---|---|
| Granite 97M | 194.9 MB + ONNX/OV extras | `model.safetensors` + configs + tokenizer |
| BitNet 270M | 367 MB | Single GGUF file + README + prompts |
| Harrier 270M | 543 MB | `model.safetensors` + `tokenizer.json` (31.8 MB) |
| Qwen3 0.6B | 1,151 MB | `model.safetensors` + `tokenizer.json` (10.9 MB) + `vocab.json` (2.6 MB) + `merges.txt` (1.6 MB) |
| MiniLM L12 | 941 MB (LFS), 2.2 GB total | `pytorch_model.bin` (449 MB) + `flax_model.msgpack` (449 MB) + `tf_model.h5` + `sentencepiece.bpe.model` (4.8 MB) |

### 6.3 Size Comparison (Relative to Current)

```
Current MiniLM L6:    91 MB   ████████
Granite 97M:         186 MB   ████████████████  (2.0×)
BitNet 270M:         350 MB   ██████████████████████████████  (3.8×)
MiniLM L12:          449 MB   ████████████████████████████████████████  (4.9×)
Harrier 270M:        511 MB   ████████████████████████████████████████████  (5.6×)
Qwen3 0.6B:         1136 MB   ██████████████████████████████████████████████████████████████████████████████████████  (12.5×)
```

---

## 7. Pooling Strategy Comparison

This directly impacts the adapter architecture design:

| Model | Architecture | Pooling | L2 Norm | Complexity |
|---|---|---|---|---|
| **Current MiniLM L6** | BERT encoder | Masked mean | Yes | Medium (mask handling) |
| **Granite 97M** | ModernBERT encoder | **CLS token** (`output[:, 0]`) | Yes | **Simple** (single index) |
| **BitNet 270M** | Gemma3 decoder | Last non-padding token | Yes | Medium (left-pad detection) |
| **Harrier 270M** | Gemma3 decoder | Last non-padding token | Yes | Medium (left-pad detection) |
| **Qwen3 0.6B** | Qwen3 decoder | Last non-padding token | Yes | Medium (left-pad detection) |
| **MiniLM L12** | BERT encoder | Masked mean | Not by default | Medium |

### Pooling Code Patterns

**CLS pooling (Granite)** — simplest:
```python
embeddings = output.last_hidden_state[:, 0, :]  # CLS at position 0
embeddings = F.normalize(embeddings, p=2, dim=1)
```

**Last-token pooling (Harrier, BitNet, Qwen3)** — more complex:
```python
def last_token_pool(last_hidden_states, attention_mask):
    left_padding = (attention_mask[:, -1].sum() == attention_mask.shape[0])
    if left_padding:
        return last_hidden_states[:, -1]
    else:
        sequence_lengths = attention_mask.sum(dim=1) - 1
        batch_size = last_hidden_states.shape[0]
        return last_hidden_states[torch.arange(batch_size), sequence_lengths]
```

**Mean pooling (current MiniLM, MiniLM L12)** — medium:
```python
def mean_pool(last_hidden_states, attention_mask):
    mask_expanded = attention_mask.unsqueeze(-1).expand(last_hidden_states.size()).float()
    sum_embeddings = torch.sum(last_hidden_states * mask_expanded, dim=1)
    sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
    return sum_embeddings / sum_mask
```

This diversity across 3 distinct pooling strategies (CLS, last-token, mean) **strongly justifies** the adapter-based `InitializedModel` trait architecture already designed in the embedding engine.

---

## 8. Candle Integration Feasibility

### 8.1 Risk Assessment

| Model | Architecture | Candle Support | Risk Level | Notes |
|---|---|---|---|---|
| **Granite 97M** | ModernBERT | ⚠️ Unknown | **Medium** | `candle-transformers` may not have `ModernBertModel`. Alternating attention + dual RoPE are non-standard. Mitigated by ONNX/OpenVINO fallback. |
| **BitNet 270M** | Gemma3 + BitLinear | ❌ Not supported | **High** | GGUF-only format. BitLinear ternary matmul not in Candle. Would require `bitnet.cpp` FFI or hand-implementing quantized kernels. |
| **Harrier 270M** | Gemma3 (Gemma3TextModel) | ⚠️ Unknown | **Medium-High** | Candle has Gemma support but Gemma3 may differ. Causal decoder architecture with sliding window. Last-token pooling is custom. |
| **Qwen3 0.6B** | Qwen3 (Qwen3ForCausalLM) | ⚠️ Unknown | **Medium** | Qwen architecture is popular, but Qwen3 is the latest iteration. Candle may lag behind. Decoder-only with tied embeddings. |
| **MiniLM L12** | BERT | ✅ Working | **None** | Identical architecture to current MiniLM L6. Drop-in replacement at the Candle level. |

### 8.2 Mitigation Paths

1. **If ModernBERT is unsupported in Candle:**
   - Granite ships ONNX models → use `onnxruntime` via PyO3 instead of Candle
   - Granite ships OpenVINO models → use OpenVINO runtime for Intel CPU optimization
   - Granite has INT8 quantized ONNX → smallest/fastest CPU option

2. **If Qwen3 is unsupported in Candle:**
   - Qwen3 has TEI (Text Embeddings Inference) support → containerized option
   - Fall back to ONNX conversion from safetensors (standard pathway)

3. **If Gemma3 is unsupported in Candle:**
   - Harrier has safetensors in a standard format — likely convertable to ONNX
   - Same for BitNet but GGUF adds complexity

---

## 9. Recommendation & Action Plan

### 9.1 Final Ranking

```
          Quality × Feasibility × Size Efficiency

  Tier 1  ⭐ Granite 97M R2
          • 186 MB, 384-dim, CLS pooling (simplest)
          • Apache 2.0, ONNX-ready, no instruction prefix
          • Risk: ModernBERT Candle support unknown
          • Concern: No explicit Gujarati enhanced training

  Tier 2  🥈 Harrier 270M
          • Best MTEB score (66.5), explicit Gujarati support
          • 511 MB, requires instruction prefix
          • Risk: Gemma3 Candle support unknown
          • Fallback if Granite fails + Gujarati matters

  Tier 3  🥉 Qwen3 0.6B
          • 8.1M downloads (community validation), MRL flexibility
          • 1,136 MB — very heavy for bundling
          • Risk: 28 layers = slower CPU inference
          • Worth testing only if Candle supports Qwen3 and Granite fails

  Watch   👀 BitNet 270M
          • Great paper specs, GGUF-only blocks Candle
          • Revisit if bitnet.cpp gets PyO3 bindings or Candle adds BitLinear

  Skip    ❌ MiniLM L12
          • Only 16 languages, no Gujarati, 449 MB for poor quality
          • Current MiniLM L6 is a better baseline
```

### 9.2 Decision Flowchart

```
  Need Gujarati? ──No──→ Use Granite 97M (if Candle works)
       │
      Yes
       │
       ├── Granite Candle OK? ──Yes──→ Benchmark Granite first
       │                                    │
       │                              Gujarati quality OK?
       │                               │ Yes        │ No
       │                               ↓            ↓
       │                           USE IT      Try Harrier
       │
       └── Granite Candle FAILS ──→ Check Harrier Candle
                                         │
                                    OK? ──Yes──→ USE Harrier
                                         │
                                        No ──→ Check Qwen3 Candle
                                                   │
                                              OK? ──Yes──→ USE Qwen3 (heavy)
                                                   │
                                                  No ──→ ONNX fallback
```

### 9.3 Immediate Next Steps

1. **Verify Candle `candle-transformers` support:**
   - Check for `modernbert` module: `grep -r "modernbert\|ModernBert" candle-transformers/src/`
   - Check for `qwen3` module: `grep -r "qwen3\|Qwen3" candle-transformers/src/`
   - Check for `gemma3` module: `grep -r "gemma3\|Gemma3" candle-transformers/src/`

2. **If ModernBERT is supported → implement Granite adapter:**
   - Add `models/granite.rs` implementing `InitializedModel`
   - CLS pooling (`output[:, 0, :]`) + L2 normalize — simpler than current mean pooling
   - Register in `registry.rs` as `"granite-embedding-97m-multilingual-r2"`
   - Run existing contract tests (`tests/integration_common.py`)

3. **If ModernBERT is NOT supported → evaluate ONNX pathway:**
   - Download Granite's `model.onnx` from HF
   - Test via `ort` (ONNX Runtime) Python bindings first
   - If viable, integrate `ort` crate into embedding engine

4. **Benchmark winner against current MiniLM L6:**
   - CPU latency (single text, batch)
   - RAM usage (model load + inference)
   - Retrieval quality on multilingual queries

---

## 10. Appendix: Raw Model Card Data

All data sourced from Hugging Face API and CLI on 2026-08-11.

### A. Granite 97M R2 (`ibm-granite/granite-embedding-97m-multilingual-r2`)

- **Created:** 2026-04-20
- **Last modified:** 2026-05-18
- **Library:** `sentence-transformers`
- **Pipeline:** `feature-extraction`
- **Auto model:** `AutoModel`
- **Processor:** `AutoTokenizer`
- **Used storage:** 1,196,158,798 bytes (~1.1 GB with ONNX/OpenVINO)
- **Spaces:** 13 leaderboards
- **Config highlights:**
  ```json
  {
    "architectures": ["ModernBertModel"],
    "model_type": "modernbert",
    "hidden_size": 384,
    "intermediate_size": 1536,
    "num_hidden_layers": 12,
    "num_attention_heads": 12,
    "hidden_activation": "silu",
    "max_position_embeddings": 32768,
    "vocab_size": 180000,
    "local_attention": 128,
    "global_attn_every_n_layers": 3,
    "global_rope_theta": 150000.0,
    "local_rope_theta": 160000.0,
    "cls_token_id": 179934,
    "bos_token_id": 179934,
    "eos_token_id": 179938,
    "sep_token_id": 179938,
    "pad_token_id": 179935
  }
  ```

### B. BitNet 270M (`microsoft/bitnet-embedding-270m`)

- **Created:** 2026-07-15
- **Last modified:** 2026-07-17
- **Library:** `transformers`
- **GGUF info:**
  ```json
  {
    "total": 268211072,
    "architecture": "gemma3",
    "context_length": 32768,
    "bos_token": "<bos>",
    "eos_token": "<eos>",
    "totalFileSize": 367487040
  }
  ```
- **Config:** No `config.json` in repo (GGUF-only release)
- **Files:** 5 total (`.gitattributes`, `README.md`, GGUF, `fig1_quant_per_task.png`, `mteb_v2_eval_prompts.json`)
- **Note:** Model card explicitly says to use `bitnet.cpp` for inference

### C. Harrier 270M (`microsoft/harrier-oss-v1-270m`)

- **Created:** 2026-03-30
- **Library:** `sentence-transformers`
- **Pipeline:** `feature-extraction`
- **Auto model:** `AutoModel`
- **Processor:** `AutoTokenizer`
- **Used storage:** 569,606,648 bytes (~543 MB)
- **Spaces:** 15
- **Config highlights:**
  ```json
  {
    "architectures": ["Gemma3TextModel"],
    "model_type": "gemma3_text",
    "hidden_size": 640,
    "intermediate_size": 2048,
    "num_hidden_layers": 18,
    "num_attention_heads": 4,
    "num_key_value_heads": 1,
    "head_dim": 256,
    "hidden_activation": "gelu_pytorch_tanh",
    "max_position_embeddings": 32768,
    "rope_theta": 1000000.0,
    "sliding_window": 512,
    "use_bidirectional_attention": false,
    "vocab_size": 262144,
    "pad_token_id": 0,
    "bos_token_id": 2,
    "eos_token_id": 1
  }
  ```
- **Key files:** `model.safetensors` (511.4 MB), `tokenizer.json` (31.8 MB)

### D. Qwen3 0.6B (`Qwen/Qwen3-Embedding-0.6B`)

- **Created:** 2025-06-03
- **Last modified:** 2026-04-20
- **Library:** `sentence-transformers`
- **Pipeline:** `feature-extraction`
- **Downloads:** 8,119,003
- **Likes:** 1,141
- **Used storage:** ~1,151 MB
- **Config highlights:**
  ```json
  {
    "architectures": ["Qwen3ForCausalLM"],
    "model_type": "qwen3",
    "hidden_size": 1024,
    "intermediate_size": 3072,
    "num_hidden_layers": 28,
    "num_attention_heads": 16,
    "num_key_value_heads": 8,
    "head_dim": 128,
    "hidden_act": "silu",
    "max_position_embeddings": 32768,
    "rope_theta": 1000000.0,
    "tie_word_embeddings": true,
    "vocab_size": 151669,
    "rms_norm_eps": 1e-06
  }
  ```
- **Key files:** `model.safetensors` (1,136.4 MB), `tokenizer.json` (10.9 MB), `vocab.json` (2.6 MB), `merges.txt` (1.6 MB)

### E. MiniLM L12 (`microsoft/Multilingual-MiniLM-L12-H384`)

- **Created:** 2022-03-02
- **Library:** `transformers`
- **Pipeline:** `text-classification`
- **Auto model:** `AutoModel`
- **Used storage:** 2,353,708,328 bytes (~2.2 GB total with JAX+TF duplicates)
- **Key files:**
  - `pytorch_model.bin`: 448.9 MB (FP32)
  - `flax_model.msgpack`: 448.9 MB (JAX)
  - `tf_model.h5`: ~900 MB (TensorFlow)
  - `sentencepiece.bpe.model`: 4.8 MB
- **Special note:** Uses `BertModel` with `XLMRobertaTokenizer` — `AutoTokenizer` is broken. Must load tokenizer explicitly: `XLMRobertaTokenizer.from_pretrained(...)`.
- **Config:** `model_type: "bert"` (standard BERT, no architectural surprises)

---

## Document Changelog

| Date | Change |
|---|---|
| 2026-08-11 | Initial report: 5-model evaluation, architecture deep-dive, language analysis, recommendations |
