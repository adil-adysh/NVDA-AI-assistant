//! Model registry — maps stable model IDs to metadata and constructors.
//!
//! Add new models by:
//! 1. Creating a module under `models/` that implements ``InitializedModel``.
//! 2. Registering the model factory in ``ModelRegistry::default()``.

use anyhow::{Context, Result};
use serde_json::Value as JsonValue;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

use hf_hub::HFClient;

use crate::models::granite::GraniteModel;
use crate::models::harrier::HarrierModel;
use crate::models::minilm::MiniLMModel;

/// Trait for a fully-initialized model ready to produce embeddings.
pub trait InitializedModel: Send + Sync {
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
}

/// Metadata describing a known model.
#[derive(Debug, Clone)]
pub struct ModelDescriptor {
    pub id: String,
    pub name: String,
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
            "name": self.name,
            "repository": self.repository,
            "architecture": self.architecture,
            "dimensions": self.dimensions,
            "max_tokens": self.max_tokens,
            "languages": self.languages,
            "model_size_mb": self.model_size_mb,
        })
    }
}

type ModelFactory = fn(&Path, usize) -> Result<Box<dyn InitializedModel>>;

const MODEL_FILES: [&str; 3] = ["config.json", "tokenizer.json", "model.safetensors"];

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
        Self::with_cache_dir(
            dirs::data_local_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("nvda")
            .join("AIAssistant")
            .join("models")
            .join("embeddings"),
        )
    }
}

impl ModelRegistry {
    pub fn with_cache_dir(cache_dir: PathBuf) -> Self {

        let mut descriptors = HashMap::new();
        let mut factories: HashMap<String, ModelFactory> = HashMap::new();

        // ── all-MiniLM-L6-v2 ──────────────────────────────────────
        let mini_lm_id = "all-MiniLM-L6-v2".to_string();
        descriptors.insert(
            mini_lm_id.clone(),
            ModelDescriptor {
                id: mini_lm_id.clone(),
                name: "all-MiniLM-L6-v2".to_string(),
                repository: "sentence-transformers/all-MiniLM-L6-v2".to_string(),
                architecture: "BERT".to_string(),
                dimensions: 384,
                max_tokens: 256,
                languages: vec!["en".to_string()],
                model_size_mb: 91.0,
            },
        );
        factories.insert(mini_lm_id, |snapshot, max_length| {
            MiniLMModel::load(snapshot, max_length).map(|model| Box::new(model) as Box<dyn InitializedModel>)
        });

        // ── granite-embedding-97m-multilingual-r2 ──────────────────
        let granite_id = "granite-embedding-97m-multilingual-r2".to_string();
        descriptors.insert(
            granite_id.clone(),
            ModelDescriptor {
                id: granite_id.clone(),
                name: "Granite 97M".to_string(),
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
        factories.insert(granite_id, |snapshot, max_length| {
            GraniteModel::load(snapshot, max_length).map(|model| Box::new(model) as Box<dyn InitializedModel>)
        });

        // ── harrier-oss-v1-270m ─────────────────────────────────────
        let harrier_id = "harrier-oss-v1-270m".to_string();
        descriptors.insert(
            harrier_id.clone(),
            ModelDescriptor {
                id: harrier_id.clone(),
                name: "Harrier OSS 270M".to_string(),
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
        factories.insert(harrier_id, |snapshot, max_length| {
            HarrierModel::load(snapshot, max_length).map(|model| Box::new(model) as Box<dyn InitializedModel>)
        });

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
    pub fn is_loaded(&self, model_id: &str) -> bool {
        self.loaded.contains_key(model_id)
    }

    pub fn load_initialized(&mut self, model_id: &str, input_limit: Option<usize>) -> Result<&dyn InitializedModel> {
        if !self.loaded.contains_key(model_id) {
            let factory = self.factories.get(model_id)
                .with_context(|| format!("Unknown model: {model_id}"))?;
            let snapshot = self.cached_snapshot(model_id)
                .with_context(|| format!("Embedding model {model_id} has not been downloaded"))?;
            let model_limit = self.descriptors[model_id].max_tokens;
            let input_limit = input_limit.unwrap_or(model_limit).min(model_limit);
            self.loaded.insert(model_id.to_string(), factory(&snapshot, input_limit)?);
        }
        Ok(self.loaded[model_id].as_ref())
    }

    /// Directory where model files are cached.
    pub fn cache_dir(&self) -> &PathBuf {
        &self.cache_dir
    }

    pub fn model_repository(&self, model_id: &str) -> Option<&str> {
        self.descriptors.get(model_id).map(|d| d.repository.as_str())
    }

    fn cached_snapshot(&self, model_id: &str) -> Option<PathBuf> {
        let repository = self.model_repository(model_id)?;
        let model_cache = self.cache_dir.join(format!("models--{}", repository.replace('/', "--")));
        let reference = std::fs::read_to_string(model_cache.join("refs").join("main")).ok()?;
        let commit = reference.trim();
        if commit.len() != 40 || !commit.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return None;
        }
        let snapshot = model_cache.join("snapshots").join(commit);
        MODEL_FILES.iter().all(|filename| {
            snapshot.join(filename).metadata().is_ok_and(|metadata| metadata.is_file() && metadata.len() > 0)
        }).then_some(snapshot)
    }

    pub fn is_cached(&self, model_id: &str) -> bool {
        self.cached_snapshot(model_id).is_some()
    }

    pub async fn download(&self, model_id: &str) -> Result<()> {
        if self.is_cached(model_id) {
            return Ok(());
        }
        let (owner, repo) = self.model_repository(model_id)
            .and_then(|repository| repository.split_once('/'))
            .with_context(|| format!("Unknown model: {model_id}"))?;
        let client = HFClient::builder().cache_dir(&self.cache_dir).build()?;
        client.model(owner, repo).snapshot_download()
            .allow_patterns(MODEL_FILES.iter().map(|file| (*file).to_owned()).collect())
            .send().await.context("Failed to download the embedding model snapshot")?;
        anyhow::ensure!(self.is_cached(model_id), "Incomplete embedding model snapshot");
        Ok(())
    }

    pub fn delete_cached(&self, model_id: &str) -> Result<()> {
        let repository = self
            .model_repository(model_id)
            .with_context(|| format!("Unknown model: {model_id}"))?;
        let cache_name = format!("models--{}", repository.replace('/', "--"));
        let model_cache = self.cache_dir.join(cache_name);
        if model_cache.exists() {
            std::fs::remove_dir_all(&model_cache)
                .with_context(|| format!("Failed to delete cache for {model_id}"))?;
        }
        Ok(())
    }
}
