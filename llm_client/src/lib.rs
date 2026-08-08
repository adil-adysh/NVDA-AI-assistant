mod client;
mod streaming;
mod types;

use pyo3::prelude::*;
use pyo3::types::PyDict;

use client::HttpClient;
use types::ChatMessage;

/// OpenAI-compatible HTTP client exposed to Python.
///
/// Communicates with any server that speaks the OpenAI `/v1/chat/completions`
/// and `/v1/models` protocol (llama.cpp server, Gemini OpenAI-compat, OpenAI).
///
/// Python usage:
///
/// ```python
/// import llm_client
/// c = llm_client.OpenAiClient(
///     base_url="http://localhost:8080/v1",
///     api_key="not-needed",
///     timeout_seconds=30.0,
/// )
/// assert c.ping() == "llm_client ready"
///
/// # Non-streaming
/// resp = c.chat_completion(
///     model="llama-3.2-3b",
///     messages=[{"role": "user", "content": "Hello"}],
/// )
/// print(resp["choices"][0]["message"]["content"])
///
/// # Streaming
/// for chunk in c.chat_completion_stream(model="...", messages=[...]):
///     delta = chunk.get("choices", [{}])[0].get("delta", {})
///     if delta.get("content"):
///         print(delta["content"], end="", flush=True)
///
/// # List models
/// models = c.list_models()
/// for m in models:
///     print(m["id"])
/// ```
#[pyclass]
struct OpenAiClient {
    http: HttpClient,
}

#[pymethods]
impl OpenAiClient {
    /// Create a new OpenAI-compatible client.
    ///
    /// Args:
    ///     base_url: Server base URL (e.g. "http://localhost:8080/v1").
    ///     api_key: API key or token (empty string for no auth, e.g. local llama.cpp).
    ///     timeout_seconds: Request timeout in seconds (default 30.0).
    #[new]
    #[pyo3(signature = (base_url, api_key = String::new(), timeout_seconds = 30.0))]
    fn new(base_url: String, api_key: String, timeout_seconds: f64) -> Self {
        Self {
            http: HttpClient::new(base_url, api_key, timeout_seconds),
        }
    }

    /// Health check — returns "llm_client ready".
    fn ping(&self) -> &'static str {
        "llm_client ready"
    }

    /// List available models via GET /v1/models.
    ///
    /// Returns a list of dicts, each with keys: ``id``, ``owned_by``, ``created``, ``object``.
    fn list_models(&self) -> PyResult<Vec<PyObject>> {
        Python::with_gil(|py| {
            let models = self.http.list_models()?;
            let result: Vec<PyObject> = models
                .iter()
                .map(|v| types::value_to_py(py, v))
                .collect();
            Ok(result)
        })
    }

    /// Send a chat completion request (non-streaming).
    ///
    /// Args:
    ///     model: Model identifier (e.g. "llama-3.2-3b", "gpt-4o").
    ///     messages: List of message dicts with ``role`` and ``content`` keys.
    ///     tools: Optional list of tool definitions in OpenAI format.
    ///     temperature: Sampling temperature (0.0–2.0).
    ///     top_p: Nucleus sampling parameter (0.0–1.0).
    ///     max_tokens: Maximum tokens to generate.
    ///     num_ctx: Context window size (Ollama).
    ///
    /// Returns:
    ///     A dict with ``choices``, ``usage``, ``model``, etc.
    #[pyo3(signature = (
        model,
        messages,
        tools = None,
        temperature = None,
        top_p = None,
        max_tokens = None,
        num_ctx = None,
    ))]
    fn chat_completion(
        &self,
        model: &str,
        messages: Vec<PyObject>,
        tools: Option<Vec<PyObject>>,
        temperature: Option<f64>,
        top_p: Option<f64>,
        max_tokens: Option<u32>,
        num_ctx: Option<u32>,
    ) -> PyResult<PyObject> {
        let chat_messages = Python::with_gil(|py| {
            messages
                .iter()
                .map(|m| py_object_to_chat_message(py, m))
                .collect::<PyResult<Vec<_>>>()
        })?;

        let tools_value: Option<Vec<serde_json::Value>> = tools
            .map(|t| {
                Python::with_gil(|py| {
                    t.iter()
                        .map(|obj| py_object_to_json_value(py, obj))
                        .collect::<PyResult<Vec<_>>>()
                })
            })
            .transpose()?;

        let response = self.http.chat_completion(
            model,
            &chat_messages,
            tools_value.as_ref(),
            temperature,
            top_p,
            max_tokens,
            num_ctx,
        )?;

        Python::with_gil(|py| Ok(types::value_to_py(py, &response)))
    }

    /// Send a streaming chat completion request.
    ///
    /// Returns an iterable that yields parsed JSON chunks (one per SSE event).
    /// Iterate with ``for chunk in client.chat_completion_stream(...)``.
    ///
    /// Args are the same as ``chat_completion``.
    #[pyo3(signature = (
        model,
        messages,
        tools = None,
        temperature = None,
        top_p = None,
        max_tokens = None,
        num_ctx = None,
    ))]
    fn chat_completion_stream(
        &self,
        model: &str,
        messages: Vec<PyObject>,
        tools: Option<Vec<PyObject>>,
        temperature: Option<f64>,
        top_p: Option<f64>,
        max_tokens: Option<u32>,
        num_ctx: Option<u32>,
    ) -> PyResult<streaming::StreamingResponse> {
        let chat_messages = Python::with_gil(|py| {
            messages
                .iter()
                .map(|m| py_object_to_chat_message(py, m))
                .collect::<PyResult<Vec<_>>>()
        })?;

        let tools_value: Option<Vec<serde_json::Value>> = tools
            .map(|t| {
                Python::with_gil(|py| {
                    t.iter()
                        .map(|obj| py_object_to_json_value(py, obj))
                        .collect::<PyResult<Vec<_>>>()
                })
            })
            .transpose()?;

        self.http.chat_completion_stream(
            model,
            &chat_messages,
            tools_value.as_ref(),
            temperature,
            top_p,
            max_tokens,
            num_ctx,
        )
    }

    /// Generic GET request — returns parsed JSON as a Python dict.
    ///
    /// ``path`` is appended to ``base_url`` (e.g. ``"/api/tags"``).
    /// Use this to call non-OpenAI endpoints (Ollama native API, health checks, etc.).
    fn get(&self, path: &str) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let value = self.http.get_json(path)?;
            Ok(types::value_to_py(py, &value))
        })
    }

    /// Generic POST request with a JSON-serializable body — returns parsed JSON as a Python dict.
    ///
    /// ``path`` is appended to ``base_url``, ``body`` must be a dict or list.
    fn post(&self, path: &str, body: PyObject) -> PyResult<PyObject> {
        let body_value = Python::with_gil(|py| py_object_to_json_value(py, &body))?;
        Python::with_gil(|py| {
            let value = self.http.post_json_body(path, &body_value)?;
            Ok(types::value_to_py(py, &value))
        })
    }
}

/// Convert a Python dict-like object to a ChatMessage.
fn py_object_to_chat_message(py: Python<'_>, obj: &PyObject) -> PyResult<ChatMessage> {
    let dict = obj.downcast_bound::<PyDict>(py).map_err(|_| {
        PyErr::new::<pyo3::exceptions::PyTypeError, _>("message must be a dict with 'role' and 'content'")
    })?;

    let role: String = dict
        .get_item("role")
        .ok()
        .flatten()
        .map(|v| v.extract())
        .transpose()
        .map_err(|_| PyErr::new::<pyo3::exceptions::PyValueError, _>("message 'role' must be a string"))?
        .unwrap_or_else(|| "user".to_string());

    let content: Option<serde_json::Value> = dict
        .get_item("content")
        .ok()
        .flatten()
        .map(|v| {
            if v.is_none() {
                Ok(None)
            } else {
                py_object_to_json_value(py, &v.into()).map(Some)
            }
        })
        .transpose()
        .map_err(|_| PyErr::new::<pyo3::exceptions::PyValueError, _>("message 'content' must be a string, array, or None"))?
        .flatten();

    let tool_calls: Option<Vec<types::ToolCall>> = dict
        .get_item("tool_calls")
        .ok()
        .flatten()
        .map(|v| py_object_to_json_value(py, &v.into()))
        .transpose()?
        .map(|v| serde_json::from_value(v).ok())
        .flatten();

    let tool_call_id: Option<String> = dict
        .get_item("tool_call_id")
        .ok()
        .flatten()
        .map(|v| v.extract())
        .transpose()
        .map_err(|_| PyErr::new::<pyo3::exceptions::PyValueError, _>("message 'tool_call_id' must be a string"))?;

    Ok(ChatMessage {
        role,
        content,
        tool_calls,
        tool_call_id,
    })
}

/// Convert a Python object to a serde_json::Value.
fn py_object_to_json_value(py: Python<'_>, obj: &PyObject) -> PyResult<serde_json::Value> {
    // Handle None
    if obj.is_none(py) {
        return Ok(serde_json::Value::Null);
    }

    // Handle bool (must check before int because bool is a subclass of int in Python)
    if let Ok(b) = obj.extract::<bool>(py) {
        return Ok(serde_json::Value::Bool(b));
    }

    // Handle int
    if let Ok(i) = obj.extract::<i64>(py) {
        return Ok(serde_json::Value::Number(serde_json::Number::from(i)));
    }

    // Handle float
    if let Ok(f) = obj.extract::<f64>(py) {
        if let Some(n) = serde_json::Number::from_f64(f) {
            return Ok(serde_json::Value::Number(n));
        }
    }

    // Handle string
    if let Ok(s) = obj.extract::<String>(py) {
        return Ok(serde_json::Value::String(s));
    }

    // Handle list
    if let Ok(list) = obj.downcast_bound::<pyo3::types::PyList>(py) {
        let items: Vec<serde_json::Value> = list
            .iter()
            .map(|item| py_object_to_json_value(py, &item.into()))
            .collect::<PyResult<Vec<_>>>()?;
        return Ok(serde_json::Value::Array(items));
    }

    // Handle dict
    if let Ok(dict) = obj.downcast_bound::<PyDict>(py) {
        let mut map = serde_json::Map::new();
        for (key, value) in dict.iter() {
            let key_str: String = key.extract().map_err(|_| {
                PyErr::new::<pyo3::exceptions::PyTypeError, _>("dict keys must be strings")
            })?;
            let json_value = py_object_to_json_value(py, &value.into())?;
            map.insert(key_str, json_value);
        }
        return Ok(serde_json::Value::Object(map));
    }

    // Fallback: try to convert via string representation
    Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
        "unsupported Python type for JSON conversion"
    ))
}

/// Python module initializer.
#[pymodule]
fn llm_client(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<OpenAiClient>()?;
    m.add_class::<streaming::StreamingResponse>()?;
    Ok(())
}
