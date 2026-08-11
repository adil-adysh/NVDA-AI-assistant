//! CPU embedding engine for NVDA AI Assistant.
//!
//! Provides a PyO3-native Rust extension that loads HuggingFace embedding
//! models via Candle and produces normalized embeddings on CPU.
//!
//! Python usage:
//!
//! ```python
//! import embedding_engine
//! engine = embedding_engine.EmbeddingEngine("all-MiniLM-L6-v2")
//! assert engine.ping() == "embedding_engine ready"
//! result = engine.embed("Hello world")
//! print(len(result))  # 384
//! results = engine.embed_batch(["text one", "text two"])
//! print(len(results), len(results[0]))  # 2, 384
//! ```

mod models;
mod pooling;
mod registry;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use registry::ModelRegistry;

fn to_py_err<E: std::fmt::Display>(error: E) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

/// Convert a `serde_json::Value` to a Python object.
fn value_to_py(py: Python<'_>, value: &serde_json::Value) -> PyObject {
    match value {
        serde_json::Value::Null => py.None(),
        serde_json::Value::Bool(b) => b.into_pyobject(py).unwrap().to_owned().into(),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.into_pyobject(py).unwrap().to_owned().into()
            } else if let Some(f) = n.as_f64() {
                f.into_pyobject(py).unwrap().to_owned().into()
            } else {
                py.None()
            }
        }
        serde_json::Value::String(s) => s.clone().into_pyobject(py).unwrap().to_owned().into(),
        serde_json::Value::Array(arr) => {
            let list: Vec<PyObject> = arr.iter().map(|v| value_to_py(py, v)).collect();
            list.into_pyobject(py).unwrap().to_owned().into()
        }
        serde_json::Value::Object(map) => {
            let dict = PyDict::new(py);
            for (k, v) in map {
                dict.set_item(k, value_to_py(py, v)).ok();
            }
            dict.into()
        }
    }
}

/// A loaded embedding model that can produce vectors for text input.
///
/// Create via ``EmbeddingEngine(model_id)``.  The engine lazily downloads
/// and loads the model on first use.
///
/// Supported model IDs are listed in ``EmbeddingEngine.available_models()``.
#[pyclass]
struct EmbeddingEngine {
    registry: ModelRegistry,
    loaded_model_id: Option<String>,
}

#[pymethods]
impl EmbeddingEngine {
    /// Create a new embedding engine.
    ///
    /// The model is **not** loaded until ``embed()`` or ``embed_batch()``
    /// is called for the first time (lazy initialization).
    ///
    /// Args:
    ///     model_id: HuggingFace model identifier, e.g. ``"all-MiniLM-L6-v2"``.
    #[new]
    fn new(model_id: String) -> PyResult<Self> {
        let registry = ModelRegistry::default();
        Ok(Self {
            registry,
            loaded_model_id: Some(model_id),
        })
    }

    /// Health-check ping.
    fn ping(&self) -> String {
        "embedding_engine ready".to_string()
    }

    /// Return the list of known model IDs that can be used with ``EmbeddingEngine``.
    #[staticmethod]
    fn available_models() -> Vec<String> {
        ModelRegistry::default().model_ids()
    }

    /// Return metadata for a specific model.
    ///
    /// Returns a dict with keys: ``id``, ``dimensions``, ``max_tokens``,
    /// ``architecture``, ``repository``.
    #[staticmethod]
    fn model_info(model_id: &str) -> PyResult<Option<PyObject>> {
        let registry = ModelRegistry::default();
        let meta = registry.model_metadata(model_id);
        Ok(meta.map(|v| Python::with_gil(|py| value_to_py(py, &v))))
    }

    /// Produce an embedding vector for a single text.
    ///
    /// Returns a ``list[float]`` of length ``self.dimensions()``.
    ///
    /// Raises ``ValueError`` for empty or whitespace-only input.
    fn embed(&mut self, text: &str) -> PyResult<Vec<f32>> {
        if text.trim().is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "Input text is empty or whitespace-only",
            ));
        }
        let results = self.embed_batch(vec![text.to_string()])?;
        results
            .into_iter()
            .next()
            .ok_or_else(|| PyRuntimeError::new_err("No embedding produced"))
    }

    /// Produce embedding vectors for multiple texts.
    ///
    /// Returns ``list[list[float]]`` — one vector per input text.
    ///
    /// Raises ``ValueError`` if any text is empty or whitespace-only.
    fn embed_batch(&mut self, texts: Vec<String>) -> PyResult<Vec<Vec<f32>>> {
        for (i, text) in texts.iter().enumerate() {
            if text.trim().is_empty() {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "Input text at index {i} is empty or whitespace-only",
                )));
            }
        }
        let model_id = self
            .loaded_model_id
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("No model selected"))?
            .clone();

        let model = self
            .registry
            .load_initialized(&model_id)
            .map_err(to_py_err)?;

        model.embed(&texts).map_err(to_py_err)
    }

    /// Number of dimensions in each embedding vector.
    fn dimensions(&self) -> PyResult<usize> {
        let model_id = self
            .loaded_model_id
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("No model selected"))?;
        let meta = self
            .registry
            .model_metadata(model_id)
            .ok_or_else(|| PyRuntimeError::new_err(format!("Unknown model: {model_id}")))?;
        Ok(meta
            .get("dimensions")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as usize)
    }

    /// Maximum number of tokens the model can accept for a single input.
    fn max_tokens(&self) -> PyResult<usize> {
        let model_id = self
            .loaded_model_id
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("No model selected"))?;
        let meta = self
            .registry
            .model_metadata(model_id)
            .ok_or_else(|| PyRuntimeError::new_err(format!("Unknown model: {model_id}")))?;
        Ok(meta
            .get("max_tokens")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as usize)
    }
}

/// Python module initialisation.
#[pymodule]
fn embedding_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<EmbeddingEngine>()?;
    Ok(())
}
