use pyo3::prelude::*;
use serde_json::Value;
use std::io::BufReader;
use std::time::Duration;

use crate::streaming::StreamingResponse;
use crate::types::*;

/// Synchronous HTTP client for OpenAI-compatible chat completion and model listing.
pub(crate) struct HttpClient {
    base_url: String,
    api_key: String,
    timeout: Duration,
}

impl HttpClient {
    pub fn new(base_url: String, api_key: String, timeout_seconds: f64) -> Self {
        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            api_key,
            timeout: Duration::from_secs_f64(timeout_seconds.max(1.0)),
        }
    }

    // ── Public API ──────────────────────────────────────────────

    /// GET /v1/models — returns raw JSON model objects.
    pub fn list_models(&self) -> PyResult<Vec<Value>> {
        let url = format!("{}/models", self.base_url);
        let (status, body) = self.get(&url)?;
        self.raise_for_status("list_models", status, &body)?;

        let parsed: ModelListResponse =
            serde_json::from_str(&body).map_err(|e| json_parse_error("list_models", &body, e))?;

        Ok(parsed
            .data
            .unwrap_or_default()
            .into_iter()
            .map(|m| serde_json::to_value(m).unwrap_or(Value::Null))
            .collect())
    }

    /// POST /v1/chat/completions (non-streaming).
    pub fn chat_completion(
        &self,
        model: &str,
        messages: &[ChatMessage],
        tools: Option<&Vec<Value>>,
        temperature: Option<f64>,
        top_p: Option<f64>,
        max_tokens: Option<u32>,
        num_ctx: Option<u32>,
    ) -> PyResult<Value> {
        let request = ChatCompletionRequest {
            model: model.to_string(),
            messages: messages.to_vec(),
            tools: tools.cloned(),
            temperature,
            top_p,
            max_tokens,
            num_ctx,
            stream: Some(false),
            stream_options: None,
        };

        let request_body = serde_json::to_string(&request)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

        let url = format!("{}/chat/completions", self.base_url);
        let (status, body) = self.post_json(&url, &request_body)?;
        self.raise_for_status("chat_completion", status, &body)?;

        let value: Value = serde_json::from_str(&body)
            .map_err(|e| json_parse_error("chat_completion", &body, e))?;

        Ok(value)
    }

    /// POST /v1/chat/completions (streaming) — returns iterator over SSE chunks.
    pub fn chat_completion_stream(
        &self,
        model: &str,
        messages: &[ChatMessage],
        tools: Option<&Vec<Value>>,
        temperature: Option<f64>,
        top_p: Option<f64>,
        max_tokens: Option<u32>,
        num_ctx: Option<u32>,
    ) -> PyResult<StreamingResponse> {
        let request = ChatCompletionRequest {
            model: model.to_string(),
            messages: messages.to_vec(),
            tools: tools.cloned(),
            temperature,
            top_p,
            max_tokens,
            num_ctx,
            stream: Some(true),
            stream_options: Some(StreamOptions {
                include_usage: true,
            }),
        };

        let request_body = serde_json::to_string(&request)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;

        let url = format!("{}/chat/completions", self.base_url);

        // For streaming, we check status before passing the reader.
        let response = self
            .build_post(&url)?
            .set("Content-Type", "application/json")
            .send_string(&request_body)
            .map_err(|e| http_error("chat_completion_stream", e))?;

        let status = response.status();
        if status >= 400 {
            let body = response
                .into_string()
                .map_err(|e| http_error("chat_completion_stream", e))?;
            self.raise_for_status("chat_completion_stream", status, &body)?;
            unreachable!();
        }

        let reader = BufReader::new(response.into_reader());
        Ok(StreamingResponse::new(reader))
    }

    /// Generic GET request returning parsed JSON.
    ///
    /// `path` is appended to `base_url` (e.g. ``"/api/tags"``).
    /// Use this to call non-OpenAI endpoints on the same server.
    pub fn get_json(&self, path: &str) -> PyResult<Value> {
        let url = format!("{}{}", self.base_url, path);
        let (status, body) = self.get(&url)?;
        self.raise_for_status("get_json", status, &body)?;

        let value: Value = serde_json::from_str(&body)
            .map_err(|e| json_parse_error("get_json", &body, e))?;
        Ok(value)
    }

    /// Generic POST request with JSON body, returning parsed JSON response.
    ///
    /// `path` is appended to `base_url` (e.g. ``"/api/chat"``).
    pub fn post_json_body(&self, path: &str, body: &Value) -> PyResult<Value> {
        let url = format!("{}{}", self.base_url, path);
        let body_str = serde_json::to_string(body)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))?;
        let (status, resp_body) = self.post_json(&url, &body_str)?;
        self.raise_for_status("post_json_body", status, &resp_body)?;

        let value: Value = serde_json::from_str(&resp_body)
            .map_err(|e| json_parse_error("post_json_body", &resp_body, e))?;
        Ok(value)
    }

    // ── HTTP helpers ────────────────────────────────────────────

    fn get(&self, url: &str) -> PyResult<(u16, String)> {
        let response = self
            .build_get(url)?
            .call()
            .map_err(|e| http_error("GET", e))?;
        let status = response.status();
        let body = response
            .into_string()
            .map_err(|e| http_error("GET", e))?;
        Ok((status, body))
    }

    fn post_json(&self, url: &str, json_body: &str) -> PyResult<(u16, String)> {
        let response = self
            .build_post(url)?
            .set("Content-Type", "application/json")
            .send_string(json_body)
            .map_err(|e| http_error("POST", e))?;
        let status = response.status();
        let body = response
            .into_string()
            .map_err(|e| http_error("POST", e))?;
        Ok((status, body))
    }

    fn build_get(&self, url: &str) -> PyResult<ureq::Request> {
        let agent = ureq::AgentBuilder::new()
            .timeout_connect(self.timeout)
            .timeout_read(self.timeout)
            .timeout_write(self.timeout)
            .build();
        let mut req = agent.get(url);
        if !self.api_key.is_empty() {
            req = req.set("Authorization", &format!("Bearer {}", self.api_key));
        }
        Ok(req)
    }

    fn build_post(&self, url: &str) -> PyResult<ureq::Request> {
        let agent = ureq::AgentBuilder::new()
            .timeout_connect(self.timeout)
            .timeout_read(self.timeout)
            .timeout_write(self.timeout)
            .build();
        let mut req = agent.post(url);
        if !self.api_key.is_empty() {
            req = req.set("Authorization", &format!("Bearer {}", self.api_key));
        }
        Ok(req)
    }

    fn raise_for_status(&self, method: &str, status: u16, body: &str) -> PyResult<()> {
        if status < 400 {
            return Ok(());
        }

        // Try OpenAI error format: {"error": {"message": "..."}}
        if let Ok(err_resp) = serde_json::from_str::<ErrorResponse>(body) {
            if let Some(detail) = err_resp.error {
                return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                    "{} HTTP {}: {}",
                    method, status, detail.message
                )));
            }
        }

        let preview: String = body.chars().take(200).collect();
        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
            "{} HTTP {}: {}",
            method, status, preview
        )))
    }
}

fn http_error(method: &str, e: impl std::fmt::Display) -> PyErr {
    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
        "{} request failed: {}",
        method, e
    ))
}

fn json_parse_error(method: &str, body: &str, e: impl std::fmt::Display) -> PyErr {
    let preview: String = body.chars().take(200).collect();
    PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
        "{} response parse error: {} — body: {}",
        method, e, preview
    ))
}
