//! Model registry — maps stable model IDs to metadata and constructors.
//!
//! Add new models by:
//! 1. Creating a module under `models/` that implements ``InitializedModel``.
//! 2. Registering the model factory in ``ModelRegistry::default()``.

use anyhow::{Context, Result};
use serde_json::Value as JsonValue;
use std::collections::HashMap;
use std::path::PathBuf;

use crate::models::granite::GraniteModel;
use crate::models::harrier::HarrierModel;
use crate::models::minilm::MiniLMModel;

/// Trait for a fully-initialized model ready to produce embeddings.
pub trait InitializedModel: Send + Sync {
    fn model_id(&self) -> &str;
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
}

/// Metadata describing a known model.
#[derive(Debug, Clone)]
pub struct ModelDescriptor {
    pub id: String,
    pub repository: String,
    pub architecture: String,
    pub dimensions: usize,
    pub max_tokens: usize,
    pub languages: Vec<String>,
    pub model_size_mb: f64,
}

impl ModelDescriptor {
    fn to_json(&self) -> JsonValue {
        serde_json::json!({
            "id": self.id,
            "repository": self.repository,
            "architecture": self.architecture,
            "dimensions": self.dimensions,
            "max_tokens": self.max_tokens,
            "languages": self.languages,
            "model_size_mb": self.model_size_mb,
        })
    }
}

type ModelFactory = Box<dyn Fn() -> Result<Box<dyn InitializedModel>> + Send + Sync>;

/// Registry of known embedding models and their metadata.
pub struct ModelRegistry {
    descriptors: HashMap<String, ModelDescriptor>,
    factories: HashMap<String, ModelFactory>,
    cache_dir: PathBuf,
    /// Lazily-initialized models (loaded on first use).
    loaded: HashMap<String, Box<dyn InitializedModel>>,
}

impl Default for ModelRegistry {
    fn default() -> Self {
        let cache_dir = dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("nvda")
            .join("AIAssistant")
            .join("models")
            .join("embeddings");

        let mut descriptors = HashMap::new();
        let mut factories: HashMap<String, ModelFactory> = HashMap::new();

        // ── all-MiniLM-L6-v2 ──────────────────────────────────────
        let mini_lm_id = "all-MiniLM-L6-v2".to_string();
        descriptors.insert(
            mini_lm_id.clone(),
            ModelDescriptor {
                id: mini_lm_id.clone(),
                repository: "sentence-transformers/all-MiniLM-L6-v2".to_string(),
                architecture: "BERT".to_string(),
                dimensions: 384,
                max_tokens: 256,
                languages: vec!["en".to_string()],
                model_size_mb: 91.0,
            },
        );
        {
            let cache = cache_dir.clone();
            factories.insert(
                mini_lm_id.clone(),
                Box::new(move || {
                    MiniLMModel::load(&cache, "all-MiniLM-L6-v2")
                        .map(|m| Box::new(m) as Box<dyn InitializedModel>)
                }),
            );
        }

        // ── granite-embedding-97m-multilingual-r2 ──────────────────
        let granite_id = "granite-embedding-97m-multilingual-r2".to_string();
        descriptors.insert(
            granite_id.clone(),
            ModelDescriptor {
                id: granite_id.clone(),
                repository: "ibm-granite/granite-embedding-97m-multilingual-r2".to_string(),
                architecture: "ModernBERT".to_string(),
                dimensions: 384,
                max_tokens: 32768,
                languages: vec![
                    "en".to_string(), "de".to_string(), "fr".to_string(),
                    "es".to_string(), "it".to_string(), "pt".to_string(),
                    "nl".to_string(), "ja".to_string(), "ko".to_string(),
                    "zh".to_string(), "ar".to_string(), "hi".to_string(),
                ],
                model_size_mb: 186.0,
            },
        );
        {
            let cache = cache_dir.clone();
            factories.insert(
                granite_id.clone(),
                Box::new(move || {
                    GraniteModel::load(&cache, "granite-embedding-97m-multilingual-r2")
                        .map(|m| Box::new(m) as Box<dyn InitializedModel>)
                }),
            );
        }

        // ── harrier-oss-v1-270m ─────────────────────────────────────
        let harrier_id = "harrier-oss-v1-270m".to_string();
        descriptors.insert(
            harrier_id.clone(),
            ModelDescriptor {
                id: harrier_id.clone(),
                repository: "microsoft/harrier-oss-v1-270m".to_string(),
                architecture: "Gemma3".to_string(),
                dimensions: 640,
                max_tokens: 32768,
                languages: vec![
                    "en".to_string(), "ar".to_string(), "de".to_string(),
                    "es".to_string(), "fr".to_string(), "hi".to_string(),
                    "it".to_string(), "ja".to_string(), "ko".to_string(),
                    "nl".to_string(), "pl".to_string(), "pt".to_string(),
                    "ru".to_string(), "th".to_string(), "tr".to_string(),
                    "vi".to_string(), "zh".to_string(),
                ],
                model_size_mb: 545.0,
            },
        );
        {
            let cache = cache_dir.clone();
            factories.insert(
                harrier_id.clone(),
                Box::new(move || {
                    HarrierModel::load(&cache, "harrier-oss-v1-270m")
                        .map(|m| Box::new(m) as Box<dyn InitializedModel>)
                }),
            );
        }

        Self {
            descriptors,
            factories,
            cache_dir,
            loaded: HashMap::new(),
        }
    }
}

impl ModelRegistry {
    /// Return all known model IDs.
    pub fn model_ids(&self) -> Vec<String> {
        self.descriptors.keys().cloned().collect()
    }

    /// Return metadata for a known model as an owned JSON value.
    pub fn model_metadata(&self, model_id: &str) -> Option<JsonValue> {
        self.descriptors.get(model_id).map(|d| d.to_json())
    }

    /// Get or initialize a model by its stable ID.
    pub fn load_initialized(&mut self, model_id: &str) -> Result<&dyn InitializedModel> {
        if !self.loaded.contains_key(model_id) {
            let factory = self
                .factories
                .remove(model_id)
                .with_context(|| format!("Unknown model: {model_id}"))?;
            let initialized = factory()?;
            self.loaded.insert(model_id.to_string(), initialized);
        }
        Ok(self.loaded[model_id].as_ref())
    }

    /// Directory where model files are cached.
    pub fn cache_dir(&self) -> &PathBuf {
        &self.cache_dir
    }
}
