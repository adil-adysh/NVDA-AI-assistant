//! Harrier OSS embedding model via local Gemma3 decoder forward pass.
//!
//! ``microsoft/harrier-oss-v1-270m``
//!
//! Downloads model files from HuggingFace Hub on first use, caches them
//! locally, and produces 640-dim normalized embeddings.
//!
//! Architecture: Gemma3 decoder → last-token pool → L2 normalize.
//! Official query instruction format:
//!   ``"Instruct: {task_description}\nQuery: {query}"``
//! Documents use raw text (no prefix).
//!
//! NOTE: candle-transformers ``gemma3::Model`` only exposes generation
//! logits via ``forward()``.  This adapter loads Gemma3 weights directly
//! via ``VarBuilder`` and implements a minimal single-pass forward for
//! hidden-state extraction.

use anyhow::{Context, Result};
use candle_core::{DType, Device, Module, Tensor, D};
use candle_nn::{linear_no_bias as linear, Linear, VarBuilder};
use hf_hub::HFClientSync;
use std::sync::Arc;
use tokenizers::Tokenizer;

use crate::pooling::last_token_pool_and_normalize;
use crate::registry::InitializedModel;

// ── RMS Normalization ──────────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct RmsNorm {
    weight: Tensor,
    eps: f64,
}

impl RmsNorm {
    fn new(hidden_size: usize, eps: f64, vb: VarBuilder) -> Result<Self> {
        let weight = vb.get(hidden_size, "weight")?;
        Ok(Self { weight, eps })
    }
}

impl Module for RmsNorm {
    fn forward(&self, xs: &Tensor) -> candle_core::Result<Tensor> {
        let dtype = xs.dtype();
        let xs_f32 = xs.to_dtype(DType::F32)?;
        let rms = (xs_f32.sqr()?.mean_keepdim(D::Minus1)? + self.eps)?.sqrt()?;
        let normalized = xs.broadcast_div(&rms.to_dtype(dtype)?)?;
        let scale = (&self.weight + 1.0)?;
        Ok(normalized.broadcast_mul(&scale.unsqueeze(0)?.unsqueeze(0)?)?)
    }
}

// ── Rotary Position Embeddings ─────────────────────────────────────────────

#[derive(Debug, Clone)]
struct RotaryEmbedding {
    sin: Tensor,
    cos: Tensor,
}

impl RotaryEmbedding {
    fn new(dtype: DType, head_dim: usize, rope_theta: f64, max_seq_len: usize, dev: &Device) -> Result<Self> {
        let inv_freq: Vec<f32> = (0..head_dim)
            .step_by(2)
            .map(|i| 1.0f32 / rope_theta.powf(i as f64 / head_dim as f64) as f32)
            .collect();
        let inv_freq_len = inv_freq.len();
        let inv_freq = Tensor::from_vec(inv_freq, (1, inv_freq_len), dev)?.to_dtype(dtype)?;
        let t = Tensor::arange(0u32, max_seq_len as u32, dev)?
            .to_dtype(dtype)?
            .unsqueeze(1)?; // (max_seq_len, 1)
        let freqs = t.matmul(&inv_freq)?; // (max_seq_len, head_dim/2)
        Ok(Self {
            sin: freqs.sin()?,
            cos: freqs.cos()?,
        })
    }

    fn apply(&self, q: &Tensor, k: &Tensor, seqlen_offset: usize) -> candle_core::Result<(Tensor, Tensor)> {
        let (_b, _n_heads, seq_len, _head_dim) = q.dims4()?;
        let sin = self.sin.narrow(0, seqlen_offset, seq_len)?.unsqueeze(0)?.unsqueeze(0)?; // (1, 1, seq_len, head_dim/2)
        let cos = self.cos.narrow(0, seqlen_offset, seq_len)?.unsqueeze(0)?.unsqueeze(0)?;
        let q_rot = apply_rotary(q, &cos, &sin)?;
        let k_rot = apply_rotary(k, &cos, &sin)?;
        Ok((q_rot, k_rot))
    }
}

fn apply_rotary(x: &Tensor, cos: &Tensor, sin: &Tensor) -> candle_core::Result<Tensor> {
    let (_b, _n, _s, d) = x.dims4()?;
    let half = d / 2;
    let x1 = x.narrow(D::Minus1, 0, half)?;
    let x2 = x.narrow(D::Minus1, half, half)?;
    let rot_x1 = (x1.broadcast_mul(cos)? - x2.broadcast_mul(sin)?)?;
    let rot_x2 = (x1.broadcast_mul(sin)? + x2.broadcast_mul(cos)?)?;
    Tensor::cat(&[&rot_x1, &rot_x2], D::Minus1)
}

// ── Gemma3 Decoder Layer (attention + MLP with pre/post norms) ─────────────

#[derive(Debug, Clone)]
struct DecoderLayer {
    self_attn: GroupedQueryAttention,
    mlp: GatedMLP,
    input_layernorm: RmsNorm,
    post_attention_layernorm: RmsNorm,
    pre_feedforward_layernorm: RmsNorm,
    post_feedforward_layernorm: RmsNorm,
    sliding_window: usize,
}

impl DecoderLayer {
    fn load(
        vb: VarBuilder,
        hidden_size: usize,
        num_heads: usize,
        num_kv_heads: usize,
        head_dim: usize,
        intermediate_size: usize,
        norm_eps: f64,
        query_pre_attn_scalar: f64,
        rope: Arc<RotaryEmbedding>,
        sliding_window: usize,
    ) -> Result<Self> {
        let self_attn = GroupedQueryAttention::load(
            vb.pp("self_attn"),
            hidden_size,
            num_heads,
            num_kv_heads,
            head_dim,
            query_pre_attn_scalar,
            rope,
        )?;
        let mlp = GatedMLP::load(vb.pp("mlp"), hidden_size, intermediate_size)?;
        let input_layernorm = RmsNorm::new(hidden_size, norm_eps, vb.pp("input_layernorm"))?;
        let post_attention_layernorm = RmsNorm::new(hidden_size, norm_eps, vb.pp("post_attention_layernorm"))?;
        let pre_feedforward_layernorm = RmsNorm::new(hidden_size, norm_eps, vb.pp("pre_feedforward_layernorm"))?;
        let post_feedforward_layernorm = RmsNorm::new(hidden_size, norm_eps, vb.pp("post_feedforward_layernorm"))?;
        Ok(Self {
            self_attn,
            mlp,
            input_layernorm,
            post_attention_layernorm,
            pre_feedforward_layernorm,
            post_feedforward_layernorm,
            sliding_window,
        })
    }

    fn forward(&self, xs: &Tensor, attn_mask: &Tensor, seqlen_offset: usize) -> candle_core::Result<Tensor> {
        let residual = xs.clone();
        let xs_norm = xs.apply(&self.input_layernorm)?;
        let attn_out = self.self_attn.forward(&xs_norm, attn_mask, seqlen_offset)?;
        // Gemma3: post_norm before residual addition
        let xs = (residual + attn_out.apply(&self.post_attention_layernorm)?)?;

        let residual = xs.clone();
        let xs_norm = xs.apply(&self.pre_feedforward_layernorm)?;
        let mlp_out = self.mlp.forward(&xs_norm)?;
        // Gemma3: post_norm before residual addition
        let xs = (residual + mlp_out.apply(&self.post_feedforward_layernorm)?)?;

        Ok(xs)
    }
}

// ── Grouped Query Attention ────────────────────────────────────────────────

#[derive(Debug, Clone)]
struct GroupedQueryAttention {
    q_proj: Linear,
    k_proj: Linear,
    v_proj: Linear,
    o_proj: Linear,
    q_norm: RmsNorm,
    k_norm: RmsNorm,
    num_heads: usize,
    num_kv_heads: usize,
    head_dim: usize,
    scale: f64,
    query_pre_attn_scalar: f64,
    rope: Arc<RotaryEmbedding>,
}

impl GroupedQueryAttention {
    fn load(
        vb: VarBuilder,
        hidden_size: usize,
        num_heads: usize,
        num_kv_heads: usize,
        head_dim: usize,
        query_pre_attn_scalar: f64,
        rope: Arc<RotaryEmbedding>,
    ) -> Result<Self> {
        let q_proj = linear(hidden_size, num_heads * head_dim, vb.pp("q_proj"))?;
        let k_proj = linear(hidden_size, num_kv_heads * head_dim, vb.pp("k_proj"))?;
        let v_proj = linear(hidden_size, num_kv_heads * head_dim, vb.pp("v_proj"))?;
        let o_proj = linear(num_heads * head_dim, hidden_size, vb.pp("o_proj"))?;
        let q_norm = RmsNorm::new(head_dim, 1e-6, vb.pp("q_norm"))?;
        let k_norm = RmsNorm::new(head_dim, 1e-6, vb.pp("k_norm"))?;
        Ok(Self {
            q_proj,
            k_proj,
            v_proj,
            o_proj,
            q_norm,
            k_norm,
            num_heads,
            num_kv_heads,
            head_dim,
            scale: 1.0 / (query_pre_attn_scalar.sqrt()),
            query_pre_attn_scalar,
            rope,
        })
    }

    fn forward(&self, xs: &Tensor, attn_mask: &Tensor, seqlen_offset: usize) -> candle_core::Result<Tensor> {
        let (b, seq_len, _) = xs.dims3()?;

        let q = xs
            .apply(&self.q_proj)?
            .reshape((b, seq_len, self.num_heads, self.head_dim))?;
        let k = xs
            .apply(&self.k_proj)?
            .reshape((b, seq_len, self.num_kv_heads, self.head_dim))?;
        let v = xs
            .apply(&self.v_proj)?
            .reshape((b, seq_len, self.num_kv_heads, self.head_dim))?;

        // Apply Q/K RMS norm (Gemma3 uses per-head normalization)
        let q = q.apply(&self.q_norm)?;
        let k = k.apply(&self.k_norm)?;

        let q = q.permute((0, 2, 1, 3))?; // (b, n_heads, seq_len, head_dim)
        let k = k.permute((0, 2, 1, 3))?;
        let v = v.permute((0, 2, 1, 3))?;

        let (q, k) = self.rope.apply(&q, &k, seqlen_offset)?;

        // Gemma3 scaling: query_pre_attn_scalar replaces head_dim in scaling.
        // Applied to QK^T product (NOT to Q alone).
        // eager_attention_forward: attn_weights = Q @ K^T * scaling
        // where scaling = query_pre_attn_scalar**-0.5 (NOT head_dim**-0.5)

        // Repeat KV heads for GQA: (b, num_kv_heads, ...) → (b, num_heads, ...)
        let n_repeats = self.num_heads / self.num_kv_heads;
        let k = repeat_kv(&k, n_repeats)?;
        let v = repeat_kv(&v, n_repeats)?;

        // Scaled dot-product attention: softmax(QK^T / sqrt(d) + mask) * V
        let attn_weights = (q.matmul(&k.t()?)? * self.scale)?;
        let attn_weights = attn_weights.broadcast_add(attn_mask)?;
        let attn_weights = candle_nn::ops::softmax(&attn_weights, D::Minus1)?;
        let attn_out = attn_weights.matmul(&v)?; // (b, n_heads, seq_len, head_dim)

        let attn_out = attn_out
            .permute((0, 2, 1, 3))?
            .reshape((b, seq_len, self.num_heads * self.head_dim))?;
        Ok(attn_out.apply(&self.o_proj)?)
    }
}

fn repeat_kv(x: &Tensor, n_repeats: usize) -> candle_core::Result<Tensor> {
    let (b, n_kv_heads, seq_len, head_dim) = x.dims4()?;
    if n_repeats == 1 {
        return Ok(x.clone());
    }
    let x = x.unsqueeze(2)?;
    let x = x.expand((b, n_kv_heads, n_repeats, seq_len, head_dim))?;
    x.reshape((b, n_kv_heads * n_repeats, seq_len, head_dim))
}

// ── Gated MLP (gelu_pytorch_tanh gating) ──────────────────────────────────

/// GELU with tanh approximation: 0.5 * x * (1 + tanh(√(2/π) * (x + 0.044715 * x³)))
fn gelu_pytorch_tanh(x: &Tensor) -> candle_core::Result<Tensor> {
    // sqrt(2/π) ≈ 0.7978845608028654
    let sqrt_2_pi = 0.7978845608028654f64;
    let x_cubed = x.mul(x)?.mul(x)?;
    let inner = (x_cubed * 0.044715)?.add(x)?;
    let tanh = (inner * sqrt_2_pi)?.tanh()?;
    let one_plus_tanh = (tanh + 1.0)?;
    (x * 0.5)?.mul(&one_plus_tanh)
}

#[derive(Debug, Clone)]
struct GatedMLP {
    gate_proj: Linear,
    up_proj: Linear,
    down_proj: Linear,
}

impl GatedMLP {
    fn load(vb: VarBuilder, hidden_size: usize, intermediate_size: usize) -> Result<Self> {
        let gate_proj = linear(hidden_size, intermediate_size, vb.pp("gate_proj"))?;
        let up_proj = linear(hidden_size, intermediate_size, vb.pp("up_proj"))?;
        let down_proj = linear(intermediate_size, hidden_size, vb.pp("down_proj"))?;
        Ok(Self { gate_proj, up_proj, down_proj })
    }

    fn forward(&self, xs: &Tensor) -> candle_core::Result<Tensor> {
        let gate = xs.apply(&self.gate_proj)?;
        let up = xs.apply(&self.up_proj)?;
        // gelu_pytorch_tanh: 0.5 * x * (1 + tanh(√(2/π) * (x + 0.044715 * x³)))
        let activated = (gelu_pytorch_tanh(&gate)? * up)?;
        Ok(activated.apply(&self.down_proj)?)
    }
}

// ── Causal Attention Mask ──────────────────────────────────────────────────

fn causal_mask(seq_len: usize, _sliding_window: usize, device: &Device) -> candle_core::Result<Tensor> {
    let mut mask_data = Vec::with_capacity(seq_len * seq_len);
    for i in 0..seq_len {
        for j in 0..seq_len {
            let val = if j > i {
                f32::NEG_INFINITY
            } else {
                0.0
            };
            mask_data.push(val);
        }
    }
    Tensor::from_slice(&mask_data, (1, 1, seq_len, seq_len), device)
}

// ── Harrier Model ──────────────────────────────────────────────────────────

pub struct HarrierModel {
    embed_tokens: candle_nn::Embedding,
    layers: Vec<DecoderLayer>,
    norm: RmsNorm,
    rope: Arc<RotaryEmbedding>,
    hidden_size: usize,
    num_heads: usize,
    num_kv_heads: usize,
    head_dim: usize,
    intermediate_size: usize,
    norm_eps: f64,
    sliding_window: usize,
    max_position_embeddings: usize,
    tokenizer: Tokenizer,
    device: Device,
    model_id: String,
}

impl HarrierModel {
    pub fn load(_cache_dir: &std::path::Path, model_id: &str) -> Result<Self> {
        let client = HFClientSync::new().context("Failed to create HF Hub client")?;
        let model = client.model("microsoft", "harrier-oss-v1-270m");

        // ── Download artifacts ──────────────────────────────────────
        let config_path = model
            .download_file()
            .filename("config.json")
            .send()
            .context("Failed to download config.json")?;
        let tokenizer_path = model
            .download_file()
            .filename("tokenizer.json")
            .send()
            .context("Failed to download tokenizer.json")?;
        let model_path = model
            .download_file()
            .filename("model.safetensors")
            .send()
            .context("Failed to download model.safetensors")?;

        // ── Parse config ────────────────────────────────────────────
        let config_str =
            std::fs::read_to_string(&config_path).context("Failed to read config.json")?;
        let raw: serde_json::Value =
            serde_json::from_str(&config_str).context("Failed to parse config.json")?;

        // Harrier uses standard Gemma3 config — read text_config if nested
        let cfg = raw
            .get("text_config")
            .unwrap_or(&raw);

        let hidden_size = cfg["hidden_size"].as_u64().unwrap_or(768) as usize;
        let num_hidden_layers = cfg["num_hidden_layers"].as_u64().unwrap_or(16) as usize;
        let num_attention_heads = cfg["num_attention_heads"].as_u64().unwrap_or(12) as usize;
        let num_key_value_heads = cfg["num_key_value_heads"].as_u64().unwrap_or(4) as usize;
        let head_dim = cfg["head_dim"].as_u64().unwrap_or(64) as usize;
        let intermediate_size = cfg["intermediate_size"].as_u64().unwrap_or(2048) as usize;
        let vocab_size = cfg["vocab_size"].as_u64().unwrap_or(256000) as usize;
        let norm_eps = cfg["rms_norm_eps"].as_f64().unwrap_or(1e-6);
        let rope_theta = cfg["rope_theta"].as_f64().unwrap_or(10_000.0);
        let sliding_window = cfg["sliding_window"].as_u64().unwrap_or(4096) as usize;
        let max_position_embeddings =
            cfg["max_position_embeddings"].as_u64().unwrap_or(8192) as usize;
        let query_pre_attn_scalar = cfg["query_pre_attn_scalar"]
            .as_f64()
            .unwrap_or((head_dim as f64).sqrt());

        // ── Load weights ────────────────────────────────────────────
        let device = Device::Cpu;
        let vb = unsafe {
            VarBuilder::from_mmaped_safetensors(&[model_path], DType::F32, &device)
        }
        .context("Failed to mmap model.safetensors")?;
        // Harrier weights are flat (no "model." prefix)
        let vb_m = &vb;

        let embed_tokens =
            candle_nn::embedding(vocab_size, hidden_size, vb_m.pp("embed_tokens"))?;

        let rope = Arc::new(RotaryEmbedding::new(
            DType::F32, head_dim, rope_theta, max_position_embeddings, &device,
        )?);

        let mut layers = Vec::with_capacity(num_hidden_layers);
        let vb_l = vb_m.pp("layers");
        for i in 0..num_hidden_layers {
            let layer = DecoderLayer::load(
                vb_l.pp(i),
                hidden_size,
                num_attention_heads,
                num_key_value_heads,
                head_dim,
                intermediate_size,
                norm_eps,
                query_pre_attn_scalar,
                rope.clone(),
                sliding_window,
            )?;
            layers.push(layer);
        }

        let norm = RmsNorm::new(hidden_size, norm_eps, vb_m.pp("norm"))?;

        let tokenizer =
            Tokenizer::from_file(&tokenizer_path).map_err(|e| anyhow::anyhow!("{e}"))?;

        Ok(Self {
            embed_tokens,
            layers,
            norm,
            rope,
            hidden_size,
            num_heads: num_attention_heads,
            num_kv_heads: num_key_value_heads,
            head_dim,
            intermediate_size,
            norm_eps,
            sliding_window,
            max_position_embeddings,
            tokenizer,
            device,
            model_id: model_id.to_string(),
        })
    }

    fn forward(&self, input_ids: &Tensor, seqlen_offset: usize) -> candle_core::Result<Tensor> {
        let (_b, seq_len) = input_ids.dims2()?;
        let attn_mask = causal_mask(seq_len, self.sliding_window, &self.device)?;

        let mut xs = self.embed_tokens.forward(input_ids)?;
        // Scale embeddings by sqrt(hidden_size) — required to match
        // SentenceTransformer reference output for Harrier.
        xs = (xs * (self.hidden_size as f64).sqrt())?;

        for layer in self.layers.iter() {
            xs = layer.forward(&xs, &attn_mask, seqlen_offset)?;
        }

        // Return hidden states before lm_head (we don't need logits)
        Ok(xs.apply(&self.norm)?)
    }
}

impl InitializedModel for HarrierModel {
    fn model_id(&self) -> &str {
        &self.model_id
    }

    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let mut all_embeddings = Vec::with_capacity(texts.len());

        // ── Tokenize ────────────────────────────────────────────────
        // Harrier uses task-specific instruction prefixes (see config_sentence_transformers.json):
        //   queries:  "Instruct: {task_description}\nQuery: {query}"
        //   documents: raw text (no prefix)
        // The caller is responsible for formatting queries with the appropriate instruction.
        for text in texts {
            let encoding = self
                .tokenizer
                .encode(text.as_str(), true)
                .map_err(|e| anyhow::anyhow!("Tokenization failed: {e}"))?;

            let input_ids =
                Tensor::new(encoding.get_ids(), &self.device)?.unsqueeze(0)?;
            let attention_mask =
                Tensor::new(encoding.get_attention_mask(), &self.device)?
                    .unsqueeze(0)?
                    .to_dtype(DType::F32)?;

            // ── Forward pass: (1, seq_len, hidden) ──────────────────
            let hidden_states = self
                .forward(&input_ids, 0)
                .map_err(|e| anyhow::anyhow!("Harrier forward pass failed: {e}"))?;

            // ── Last-token pool + L2 normalize → (1, hidden) ───────
            let normalized =
                last_token_pool_and_normalize(&hidden_states, &attention_mask)?;

            // ── Convert to Vec<f32> ─────────────────────────────────
            let embedding: Vec<f32> = normalized
                .flatten_all()
                .context("Flatten embedding failed")?
                .to_vec1()
                .context("to_vec1 failed")?;

            all_embeddings.push(embedding);
        }

        Ok(all_embeddings)
    }
}
