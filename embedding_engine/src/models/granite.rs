//! Granite embedding model with self-contained ModernBERT encoder.
//!
//! ``ibm-granite/granite-embedding-97m-multilingual-r2``
//!
//! Downloads model files from HuggingFace Hub on first use, caches them
//! locally, and produces 384-dim normalized embeddings.
//!
//! Architecture: ModernBERT encoder → CLS pool → L2 normalize.
//! No instruction prefix needed.
//!
//! NOTE: candle-transformers' ``ModernBert::load`` hardcodes a ``model.``
//! prefix on all weight paths, but Granite's safetensors use flat keys
//! (no prefix).  This module implements the ModernBERT encoder directly
//! with correct flat VarBuilder paths.

use anyhow::{Context, Result};
use candle_core::{DType, Device, Tensor, D};
use candle_nn::{
    embedding, layer_norm_no_bias, linear_no_bias, ops::softmax, Embedding, LayerNorm, Linear,
    Module, VarBuilder,
};
use candle_transformers::models::modernbert::Config;
use hf_hub::HFClientSync;
use std::sync::Arc;
use tokenizers::Tokenizer;

use crate::pooling::cls_pool_and_normalize;
use crate::registry::InitializedModel;

// ── Rotary Position Embeddings ─────────────────────────────────────────────

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
            .reshape((max_seq_len, 1))?;
        let freqs = t.matmul(&inv_freq)?;
        Ok(Self {
            sin: freqs.sin()?,
            cos: freqs.cos()?,
        })
    }

    fn apply(&self, q: &Tensor, k: &Tensor) -> Result<(Tensor, Tensor)> {
        let q_embed = candle_nn::rotary_emb::rope(&q.contiguous()?, &self.cos, &self.sin)?;
        let k_embed = candle_nn::rotary_emb::rope(&k.contiguous()?, &self.cos, &self.sin)?;
        Ok((q_embed, k_embed))
    }
}

// ── Attention ──────────────────────────────────────────────────────────────

struct GraniteAttention {
    qkv: Linear,
    proj: Linear,
    num_attention_heads: usize,
    attention_head_size: usize,
    rotary_emb: Arc<RotaryEmbedding>,
}

impl GraniteAttention {
    fn load(vb: VarBuilder, config: &Config, rotary_emb: Arc<RotaryEmbedding>) -> Result<Self> {
        let num_attention_heads = config.num_attention_heads;
        let attention_head_size = config.hidden_size / config.num_attention_heads;

        let qkv = linear_no_bias(config.hidden_size, config.hidden_size * 3, vb.pp("Wqkv"))?;
        let proj = linear_no_bias(config.hidden_size, config.hidden_size, vb.pp("Wo"))?;

        Ok(Self {
            qkv,
            proj,
            num_attention_heads,
            attention_head_size,
            rotary_emb,
        })
    }

    fn forward(&self, hidden_states: &Tensor, attention_mask: &Tensor) -> Result<Tensor> {
        let (b, seq_len, d) = hidden_states.dims3()?;

        let qkv = hidden_states
            .apply(&self.qkv)?
            .reshape((
                b,
                seq_len,
                3,
                self.num_attention_heads,
                self.attention_head_size,
            ))?
            .permute((2, 0, 3, 1, 4))?;

        let q = qkv.get(0)?;
        let k = qkv.get(1)?;
        let v = qkv.get(2)?;

        let (q, k) = self.rotary_emb.apply(&q, &k)?;

        let scale = (self.attention_head_size as f64).powf(-0.5);
        let q = (q * scale)?;

        let att = q.matmul(&k.transpose(D::Minus2, D::Minus1)?)?;
        let att = att.broadcast_add(attention_mask)?;
        let att = softmax(&att, D::Minus1)?;

        let xs = att.matmul(&v)?;
        let xs = xs.transpose(1, 2)?.reshape((b, seq_len, d))?;
        let xs = xs.apply(&self.proj)?;

        Ok(xs)
    }
}

// ── MLP (GeGLU) ────────────────────────────────────────────────────────────

struct GraniteMLP {
    wi: Linear,
    wo: Linear,
}

impl GraniteMLP {
    fn load(vb: VarBuilder, config: &Config) -> Result<Self> {
        let wi = linear_no_bias(
            config.hidden_size,
            config.intermediate_size * 2,
            vb.pp("Wi"),
        )?;
        let wo = linear_no_bias(config.intermediate_size, config.hidden_size, vb.pp("Wo"))?;
        Ok(Self { wi, wo })
    }
}

impl Module for GraniteMLP {
    fn forward(&self, xs: &Tensor) -> candle_core::Result<Tensor> {
        let xs = xs.apply(&self.wi)?;
        let xs = xs.chunk(2, D::Minus1)?;
        let xs = (xs[0].gelu_erf()? * &xs[1])?.apply(&self.wo)?;
        Ok(xs)
    }
}

// ── Decoder Layer ──────────────────────────────────────────────────────────

struct GraniteLayer {
    attn: GraniteAttention,
    mlp: GraniteMLP,
    attn_norm: Option<LayerNorm>,
    mlp_norm: LayerNorm,
    uses_local_attention: bool,
}

impl GraniteLayer {
    fn load(
        vb: VarBuilder,
        config: &Config,
        rotary_emb: Arc<RotaryEmbedding>,
        uses_local_attention: bool,
    ) -> Result<Self> {
        let attn = GraniteAttention::load(vb.pp("attn"), config, rotary_emb)?;
        let mlp = GraniteMLP::load(vb.pp("mlp"), config)?;
        let attn_norm = layer_norm_no_bias(
            config.hidden_size,
            config.layer_norm_eps,
            vb.pp("attn_norm"),
        )
        .ok();
        let mlp_norm =
            layer_norm_no_bias(config.hidden_size, config.layer_norm_eps, vb.pp("mlp_norm"))?;
        Ok(Self {
            attn,
            mlp,
            attn_norm,
            mlp_norm,
            uses_local_attention,
        })
    }

    fn forward(
        &self,
        xs: &Tensor,
        global_attention_mask: &Tensor,
        local_attention_mask: &Tensor,
    ) -> Result<Tensor> {
        let residual = xs.clone();
        let mut xs = xs.clone();
        if let Some(norm) = &self.attn_norm {
            xs = xs.apply(norm)?;
        }

        let attention_mask = if self.uses_local_attention {
            &global_attention_mask.broadcast_add(local_attention_mask)?
        } else {
            global_attention_mask
        };
        let xs = self.attn.forward(&xs, attention_mask)?;
        let xs = (xs + residual)?;
        let mlp_out = xs.apply(&self.mlp_norm)?.apply(&self.mlp)?;
        let xs = (xs + mlp_out)?;
        Ok(xs)
    }
}

// ── Attention Mask Helpers ─────────────────────────────────────────────────

fn prepare_4d_attention_mask(
    mask: &Tensor,
    dtype: DType,
    tgt_len: Option<usize>,
) -> Result<Tensor> {
    let bsz = mask.dim(0)?;
    let src_len = mask.dim(1)?;
    let tgt_len = tgt_len.unwrap_or(src_len);

    let expanded_mask = mask
        .unsqueeze(1)?
        .unsqueeze(2)?
        .expand((bsz, 1, tgt_len, src_len))?
        .to_dtype(dtype)?;

    let inverted_mask = (1.0 - expanded_mask)?;

    Ok((inverted_mask * f32::MIN as f64)?.to_dtype(dtype)?)
}

fn get_local_attention_mask(
    seq_len: usize,
    max_distance: usize,
    device: &Device,
) -> Result<Tensor> {
    let mask: Vec<f32> = (0..seq_len)
        .flat_map(|i| {
            (0..seq_len).map(move |j| {
                if (j as i32 - i as i32).abs() > max_distance as i32 {
                    f32::NEG_INFINITY
                } else {
                    0.0
                }
            })
        })
        .collect();
    Ok(Tensor::from_slice(&mask, (seq_len, seq_len), device)?)
}

// ── Granite Model ──────────────────────────────────────────────────────────

/// A loaded Granite embedding model.
///
/// Created via [`GraniteModel::load`] which downloads model artifacts
/// from HuggingFace Hub on first use and caches them via ``hf_hub``.
pub struct GraniteModel {
    word_embeddings: Embedding,
    norm: LayerNorm,
    layers: Vec<GraniteLayer>,
    final_norm: LayerNorm,
    local_attention_size: usize,
    tokenizer: Tokenizer,
    device: Device,
    model_id: String,
}

impl GraniteModel {
    /// Download (if needed) and load the Granite model.
    pub fn load(_cache_dir: &std::path::Path, model_id: &str) -> Result<Self> {
        let client = HFClientSync::new().context("Failed to create HF Hub client")?;

        // Granite 97M multilingual R2
        let model = client.model("ibm-granite", "granite-embedding-97m-multilingual-r2");

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
        let config: Config = {
            let config_str =
                std::fs::read_to_string(&config_path).context("Failed to read config.json")?;
            serde_json::from_str(&config_str).context("Failed to parse config.json")?
        };

        // ── Load weights with FLAT paths (no "model." prefix) ───────
        let device = Device::Cpu;
        let vb = unsafe {
            VarBuilder::from_mmaped_safetensors(&[model_path], DType::F32, &device)
        }
        .context("Failed to mmap model.safetensors")?;

        let word_embeddings = embedding(
            config.vocab_size,
            config.hidden_size,
            vb.pp("embeddings.tok_embeddings"),
        )?;
        let norm = layer_norm_no_bias(
            config.hidden_size,
            config.layer_norm_eps,
            vb.pp("embeddings.norm"),
        )?;

        let global_rotary_emb = Arc::new(RotaryEmbedding::new(
            vb.dtype(),
            config.hidden_size / config.num_attention_heads,
            config.global_rope_theta,
            config.max_position_embeddings,
            vb.device(),
        )?);
        let local_rotary_emb = Arc::new(RotaryEmbedding::new(
            vb.dtype(),
            config.hidden_size / config.num_attention_heads,
            config.local_rope_theta,
            config.max_position_embeddings,
            vb.device(),
        )?);

        let mut layers = Vec::with_capacity(config.num_hidden_layers);
        for layer_id in 0..config.num_hidden_layers {
            let uses_local = layer_id % config.global_attn_every_n_layers != 0;
            let rope = if uses_local {
                local_rotary_emb.clone()
            } else {
                global_rotary_emb.clone()
            };
            layers.push(GraniteLayer::load(
                vb.pp(format!("layers.{layer_id}")),
                &config,
                rope,
                uses_local,
            )?);
        }

        let final_norm = layer_norm_no_bias(
            config.hidden_size,
            config.layer_norm_eps,
            vb.pp("final_norm"),
        )?;

        // ── Load tokenizer ──────────────────────────────────────────
        let tokenizer =
            Tokenizer::from_file(&tokenizer_path).map_err(|e| anyhow::anyhow!("{e}"))?;

        Ok(Self {
            word_embeddings,
            norm,
            layers,
            final_norm,
            local_attention_size: config.local_attention,
            tokenizer,
            device,
            model_id: model_id.to_string(),
        })
    }

    fn forward(&self, input_ids: &Tensor, attention_mask: &Tensor) -> Result<Tensor> {
        let seq_len = input_ids.dims()[1];
        let global_attention_mask =
            prepare_4d_attention_mask(attention_mask, DType::F32, None)?
                .to_device(input_ids.device())?;
        let local_attention_mask =
            get_local_attention_mask(seq_len, self.local_attention_size / 2, input_ids.device())?;

        let mut xs = input_ids
            .apply(&self.word_embeddings)?
            .apply(&self.norm)?;
        for layer in self.layers.iter() {
            xs = layer.forward(&xs, &global_attention_mask, &local_attention_mask)?;
        }
        let xs = xs.apply(&self.final_norm)?;
        Ok(xs)
    }
}

// ── InitializedModel impl ──────────────────────────────────────────────────

impl InitializedModel for GraniteModel {
    fn model_id(&self) -> &str {
        &self.model_id
    }

    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let mut all_embeddings = Vec::with_capacity(texts.len());

        // ── Tokenize with padding to longest sequence ───────────────
        let encodings: Vec<_> = texts
            .iter()
            .map(|t| {
                self.tokenizer
                    .encode(t.as_str(), true)
                    .map_err(|e| anyhow::anyhow!("Tokenization failed: {e}"))
            })
            .collect::<Result<Vec<_>>>()?;

        let max_len = encodings.iter().map(|e| e.len()).max().unwrap_or(1);

        for encoding in &encodings {
            let mut ids = encoding.get_ids().to_vec();
            let mut mask = encoding.get_attention_mask().to_vec();

            // Pad to max_len
            ids.resize(max_len, 0);
            mask.resize(max_len, 0);

            let input_ids =
                Tensor::new(&ids[..], &self.device)?.unsqueeze(0)?; // (1, seq_len)
            let attention_mask = Tensor::new(&mask[..], &self.device)?
                .unsqueeze(0)? // (1, seq_len)
                .to_dtype(DType::F32)?;

            // ── Forward pass: (1, seq_len, hidden) ──────────────────
            let hidden_states = self
                .forward(&input_ids, &attention_mask)
                .context("ModernBERT forward pass failed")?;

            // ── CLS pool + L2 normalize → (1, hidden) ──────────────
            let normalized = cls_pool_and_normalize(&hidden_states)?;

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

