//! MiniLM embedding model via Candle BERT.
//!
//! Downloads model files from HuggingFace Hub on first use,
//! caches them locally, and produces 384-dim normalized embeddings.
//!
//! Architecture: BERT → mean pool over token embeddings → L2 normalize.
//! This matches the Sentence-BERT pipeline used by sentence-transformers.

use anyhow::{Context, Result};
use candle_core::{Device, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::bert::{BertModel, Config};
use super::load_tokenizer;
use tokenizers::Tokenizer;

use crate::pooling::pool_and_normalize;
use crate::registry::InitializedModel;

/// A loaded MiniLM model ready to produce sentence embeddings.
///
/// Created via [`MiniLMModel::load`] from a complete Hugging Face model snapshot.
pub struct MiniLMModel {
    model: BertModel,
    tokenizer: Tokenizer,
    device: Device,
}

impl MiniLMModel {
    /// Load MiniLM from a complete model snapshot.
    pub fn load(snapshot: &std::path::Path, max_length: usize) -> Result<Self> {
        let config_path = snapshot.join("config.json");
        let tokenizer_path = snapshot.join("tokenizer.json");
        let model_path = snapshot.join("model.safetensors");

        // ── Parse config ────────────────────────────────────────────
        let config: Config = {
            let config_str =
                std::fs::read_to_string(&config_path).context("Failed to read config.json")?;
            serde_json::from_str(&config_str).context("Failed to parse config.json")?
        };

        // ── Load model weights via VarBuilder ────────────────────────
        let device = Device::Cpu;
        // SAFETY: model_path points to a valid safetensors file
        // downloaded from HuggingFace Hub. The memory mapping is
        // read-only and the file outlives the VarBuilder.
        let vb = unsafe {
            VarBuilder::from_mmaped_safetensors(
                &[model_path],
                candle_core::DType::F32,
                &device,
            )
        }
        .context("Failed to mmap model.safetensors")?;
        let model =
            BertModel::load(vb, &config).context("Failed to load BertModel from weights")?;

        // ── Load tokenizer ──────────────────────────────────────────
        let tokenizer =
            load_tokenizer(&tokenizer_path, max_length)?;

        Ok(Self {
            model,
            tokenizer,
            device,
        })
    }
}

impl InitializedModel for MiniLMModel {
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let mut all_embeddings = Vec::with_capacity(texts.len());

        for text in texts {
            // ── Tokenize ────────────────────────────────────────────
            let encoding = self
                .tokenizer
                .encode(text.as_str(), true)
                .map_err(|e| anyhow::anyhow!("Tokenization failed: {e}"))?;

            let input_ids =
                Tensor::new(encoding.get_ids(), &self.device)?.unsqueeze(0)?;
            let token_type_ids = Tensor::zeros(
                input_ids.shape(),
                candle_core::DType::U32,
                &self.device,
            )?;
            let attention_mask =
                Tensor::new(encoding.get_attention_mask(), &self.device)?
                    .unsqueeze(0)?
                    .to_dtype(candle_core::DType::F32)?;

            // ── Forward pass: (1, seq_len, hidden) ──────────────────
            let hidden_states = self
                .model
                .forward(&input_ids, &token_type_ids, Some(&attention_mask))
                .context("BERT forward pass failed")?;

            // ── Mean pool + L2 normalize → (1, hidden) ──────────────
            let pooled = pool_and_normalize(&hidden_states, &attention_mask)?;

            // ── Convert to Vec<f32> ─────────────────────────────────
            let embedding: Vec<f32> = pooled
                .flatten_all()
                .context("Flatten embedding failed")?
                .to_vec1()
                .context("to_vec1 failed")?;

            all_embeddings.push(embedding);
        }

        Ok(all_embeddings)
    }
}
