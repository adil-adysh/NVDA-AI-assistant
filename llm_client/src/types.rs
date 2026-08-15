#![allow(dead_code)]

use pyo3::prelude::*;
#[allow(deprecated)]
use pyo3::IntoPy;
use serde::{Deserialize, Serialize};

/// A chat message as sent to the OpenAI-compatible endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct ChatMessage {
    pub role: String,
    /// Content can be a string or an array of content parts (for multimodal).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_calls: Option<Vec<ToolCall>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
}

/// A tool call within an assistant message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct ToolCall {
    pub id: String,
    #[serde(rename = "type")]
    pub call_type: String,
    pub function: ToolCallFunction,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct ToolCallFunction {
    pub name: String,
    pub arguments: String,
}

/// Request body for /v1/chat/completions.
#[derive(Debug, Clone, Serialize)]
pub(crate) struct ChatCompletionRequest {
    pub model: String,
    pub messages: Vec<ChatMessage>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tools: Option<Vec<serde_json::Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub top_p: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub num_ctx: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub top_k: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub repeat_penalty: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stream: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stream_options: Option<StreamOptions>,
    #[serde(flatten, skip_serializing_if = "serde_json::Map::is_empty")]
    pub extra: serde_json::Map<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct StreamOptions {
    pub include_usage: bool,
}

/// Parsed SSE chunk from a streaming response.
#[derive(Debug, Clone, Deserialize)]
pub(crate) struct StreamChunk {
    pub id: Option<String>,
    pub object: Option<String>,
    pub created: Option<i64>,
    pub model: Option<String>,
    pub choices: Option<Vec<StreamChoice>>,
    pub usage: Option<UsageInfo>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct StreamChoice {
    pub index: Option<u32>,
    pub delta: Option<StreamDelta>,
    pub finish_reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct StreamDelta {
    pub role: Option<String>,
    pub content: Option<String>,
    pub tool_calls: Option<Vec<ToolCallDelta>>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ToolCallDelta {
    pub index: Option<u32>,
    pub id: Option<String>,
    #[serde(rename = "type")]
    pub call_type: Option<String>,
    pub function: Option<ToolCallFunctionDelta>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ToolCallFunctionDelta {
    pub name: Option<String>,
    pub arguments: Option<String>,
}

/// Full (non-streaming) chat completion response.
#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ChatCompletionResponse {
    pub id: Option<String>,
    pub object: Option<String>,
    pub created: Option<i64>,
    pub model: Option<String>,
    pub choices: Option<Vec<Choice>>,
    pub usage: Option<UsageInfo>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct Choice {
    pub index: Option<u32>,
    pub message: Option<ResponseMessage>,
    pub finish_reason: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ResponseMessage {
    pub role: Option<String>,
    pub content: Option<String>,
    pub tool_calls: Option<Vec<ToolCall>>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct UsageInfo {
    pub prompt_tokens: Option<u32>,
    pub completion_tokens: Option<u32>,
    pub total_tokens: Option<u32>,
}

/// Response from /v1/models.
#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ModelListResponse {
    pub object: Option<String>,
    pub data: Option<Vec<ModelInfo>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub(crate) struct ModelInfo {
    pub id: Option<String>,
    pub object: Option<String>,
    pub created: Option<i64>,
    pub owned_by: Option<String>,
}

/// Error response from OpenAI-compatible endpoints.
#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ErrorResponse {
    pub error: Option<ErrorDetail>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct ErrorDetail {
    pub message: String,
    #[serde(rename = "type")]
    pub error_type: Option<String>,
    pub code: Option<String>,
}

/// Converts a serde_json::Value to a Python object.
pub(crate) fn value_to_py(py: Python<'_>, value: &serde_json::Value) -> PyObject {
    match value {
        serde_json::Value::Null => py.None(),
        serde_json::Value::Bool(b) => (*b).into_py(py),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.into_py(py)
            } else if let Some(f) = n.as_f64() {
                f.into_py(py)
            } else {
                py.None()
            }
        }
        serde_json::Value::String(s) => s.clone().into_py(py),
        serde_json::Value::Array(arr) => {
            let list: Vec<PyObject> = arr.iter().map(|v| value_to_py(py, v)).collect();
            list.into_py(py)
        }
        serde_json::Value::Object(map) => {
            let dict = pyo3::types::PyDict::new(py);
            for (k, v) in map {
                dict.set_item(k, value_to_py(py, v)).ok();
            }
            dict.into()
        }
    }
}

/// Converts a serde_json::Value to a PyObject (must be a dict or list).
pub(crate) fn json_to_py(py: Python<'_>, json: &str) -> PyResult<PyObject> {
    let value: serde_json::Value =
        serde_json::from_str(json).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
    Ok(value_to_py(py, &value))
}
