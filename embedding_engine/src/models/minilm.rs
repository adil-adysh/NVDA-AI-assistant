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
use hf_hub::HFClientSync;
use tokenizers::Tokenizer;

use crate::pooling::pool_and_normalize;
use crate::registry::InitializedModel;

/// A loaded MiniLM model ready to produce sentence embeddings.
///
/// Created via [`MiniLMModel::load`] which downloads model artifacts
/// from HuggingFace Hub on first use and caches them via ``hf_hub``.
pub struct MiniLMModel {
    model: BertModel,
    tokenizer: Tokenizer,
    device: Device,
    model_id: String,
}

impl MiniLMModel {
    /// Download (if needed) and load the MiniLM model.
    ///
    /// * `cache_dir` — currently unused; ``hf_hub`` manages its own cache.
    /// * `model_id` — HuggingFace model ID (e.g. ``"all-MiniLM-L6-v2"``).
    pub fn load(_cache_dir: &std::path::Path, model_id: &str) -> Result<Self> {
        let client =
            HFClientSync::new().context("Failed to create HF Hub client")?;
        let model = client.model("sentence-transformers", model_id);

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
            Tokenizer::from_file(&tokenizer_path).map_err(|e| anyhow::anyhow!("{e}"))?;

        Ok(Self {
            model,
            tokenizer,
            device,
            model_id: model_id.to_string(),
        })
    }
}

impl InitializedModel for MiniLMModel {
    fn model_id(&self) -> &str {
        &self.model_id
    }

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
