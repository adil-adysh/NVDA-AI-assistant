use pyo3::prelude::*;
use serde_json::Value;
use std::io::{BufRead, BufReader, Read};

use crate::types::*;

/// Python-iterable SSE streaming response.
///
/// Holds the HTTP response body reader and yields parsed JSON chunks
/// one at a time via Python's iterator protocol (`__iter__` / `__next__`).
/// Marked `unsendable` because the underlying HTTP reader is not `Sync`.
#[pyclass(unsendable)]
pub(crate) struct StreamingResponse {
    reader: BufReader<Box<dyn Read + Send>>,
    done: bool,
}

impl StreamingResponse {
    pub fn new<R: Read + Send + 'static>(reader: BufReader<R>) -> Self {
        Self {
            reader: BufReader::new(Box::new(reader.into_inner())),
            done: false,
        }
    }

    /// Read one SSE event from the stream. Returns the parsed JSON value
    /// or None when the stream ends (`data: [DONE]`).
    fn read_next_chunk(&mut self) -> PyResult<Option<Value>> {
        let mut line = String::new();

        loop {
            line.clear();
            let bytes_read = self
                .reader
                .read_line(&mut line)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    format!("SSE read error: {}", e)
                ))?;

            if bytes_read == 0 {
                // EOF
                return Ok(None);
            }

            let trimmed = line.trim();

            // Empty line between events — continue reading
            if trimmed.is_empty() {
                continue;
            }

            // Comment line — skip
            if trimmed.starts_with(':') {
                continue;
            }

            // Must be a `data:` line
            if let Some(data) = trimmed.strip_prefix("data:") {
                let data = data.trim();

                // End of stream marker
                if data == "[DONE]" {
                    return Ok(None);
                }

                // Try parsing as a stream chunk
                let chunk: Value = serde_json::from_str(data).map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                        "SSE JSON parse error: {} — data: {}",
                        e,
                        data.chars().take(200).collect::<String>()
                    ))
                })?;

                return Ok(Some(chunk));
            }

            // Unknown line prefix — skip
        }
    }
}

#[pymethods]
impl StreamingResponse {
    /// Python `__iter__` — returns self.
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    /// Python `__next__` — yields the next SSE chunk as a Python dict,
    /// or raises `StopIteration` when the stream ends.
    fn __next__(mut slf: PyRefMut<'_, Self>) -> PyResult<Option<PyObject>> {
        if slf.done {
            return Ok(None);
        }

        match slf.read_next_chunk()? {
            Some(value) => {
                let py = slf.py();
                Ok(Some(value_to_py(py, &value)))
            }
            None => {
                slf.done = true;
                Ok(None)
            }
        }
    }
}
