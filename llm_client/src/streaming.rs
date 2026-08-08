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

}

/// Read one chunk without borrowing the Python wrapper.  This lets the
/// iterator move its blocking socket read outside the Python GIL.
fn read_next_chunk_from_reader(
    reader: &mut BufReader<Box<dyn Read + Send>>,
) -> PyResult<Option<Value>> {
    let mut line = String::new();

    loop {
        line.clear();
        let bytes_read = reader
            .read_line(&mut line)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                format!("SSE read error: {}", e),
            ))?;

        if bytes_read == 0 {
            return Ok(None);
        }
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with(':') {
            continue;
        }
        if let Some(data) = trimmed.strip_prefix("data:") {
            let data = data.trim();
            if data == "[DONE]" {
                return Ok(None);
            }
            let chunk: Value = serde_json::from_str(data).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "SSE JSON parse error: {} — data: {}",
                    e,
                    data.chars().take(200).collect::<String>()
                ))
            })?;
            return Ok(Some(chunk));
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

        // PyRefMut cannot cross the GIL-release closure. Temporarily move the
        // reader out of the Python wrapper, perform the blocking read, then
        // put it back before converting the result to a Python object.
        let mut reader = std::mem::replace(
            &mut slf.reader,
            BufReader::new(Box::new(std::io::empty())),
        );
        let result = slf.py().allow_threads(|| read_next_chunk_from_reader(&mut reader));
        slf.reader = reader;

        match result? {
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
