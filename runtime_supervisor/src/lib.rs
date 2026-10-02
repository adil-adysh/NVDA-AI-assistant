pub mod health;
pub mod process;
pub mod supervisor;
pub mod types;

#[cfg(test)]
mod tests;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

pub use supervisor::SupervisorCore;
pub use types::{LifecycleState, RuntimeStatus};

#[pyclass]
pub struct RuntimeSupervisor {
    core: Arc<SupervisorCore>,
}

#[pymethods]
impl RuntimeSupervisor {
    #[new]
    #[pyo3(signature = (runtime_name, host = "127.0.0.1".to_string(), port = 9379))]
    pub fn new(runtime_name: String, host: String, port: u16) -> Self {
        Self {
            core: Arc::new(SupervisorCore::new(runtime_name, host, port)),
        }
    }

    #[getter]
    pub fn base_url(&self) -> String {
        self.core.base_url().to_string()
    }

    #[getter]
    pub fn runtime_name(&self) -> String {
        self.core.runtime_name().to_string()
    }

    #[getter]
    pub fn host(&self) -> String {
        self.core.host().to_string()
    }

    #[getter]
    pub fn port(&self) -> u16 {
        self.core.port()
    }

    /// Read-only snapshot of supervisor status (non-blocking, safe for NVDA main thread).
    pub fn status(&self) -> RuntimeStatus {
        self.core.status()
    }

    /// Check if current owned process matches the startup identity.
    pub fn matches_startup_configuration(&self, startup_identity: &str) -> bool {
        self.core.matches_startup_configuration(startup_identity)
    }

    /// Ensure runtime is running and healthy. Deduplicates concurrent callers.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (executable, args, env, startup_identity, running_model = None, timeout_seconds = None))]
    pub fn ensure_ready(
        &self,
        py: Python<'_>,
        executable: String,
        args: Vec<String>,
        env: HashMap<String, String>,
        startup_identity: String,
        running_model: Option<String>,
        timeout_seconds: Option<f64>,
    ) -> PyResult<RuntimeStatus> {
        let timeout = Duration::from_secs_f64(timeout_seconds.unwrap_or(60.0).max(0.1));
        let core = Arc::clone(&self.core);

        py.allow_threads(move || {
            core.ensure_ready(
                &executable,
                &args,
                &env,
                &startup_identity,
                running_model.as_deref(),
                timeout,
            )
        })
        .map_err(PyRuntimeError::new_err)
    }

    /// Restart the runtime with fresh configuration.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (executable, args, env, startup_identity, running_model = None, timeout_seconds = None))]
    pub fn restart(
        &self,
        py: Python<'_>,
        executable: String,
        args: Vec<String>,
        env: HashMap<String, String>,
        startup_identity: String,
        running_model: Option<String>,
        timeout_seconds: Option<f64>,
    ) -> PyResult<RuntimeStatus> {
        let timeout = Duration::from_secs_f64(timeout_seconds.unwrap_or(60.0).max(0.1));
        let core = Arc::clone(&self.core);

        py.allow_threads(move || {
            core.restart(
                &executable,
                &args,
                &env,
                &startup_identity,
                running_model.as_deref(),
                timeout,
            )
        })
        .map_err(PyRuntimeError::new_err)
    }

    /// Stop the server process gracefully, then forcefully if needed.
    #[pyo3(signature = (timeout_seconds = None))]
    pub fn stop(&self, py: Python<'_>, timeout_seconds: Option<f64>) -> PyResult<RuntimeStatus> {
        let timeout = Duration::from_secs_f64(timeout_seconds.unwrap_or(10.0).max(0.1));
        let core = Arc::clone(&self.core);

        py.allow_threads(move || core.stop(timeout))
            .map_err(PyRuntimeError::new_err)
    }

    /// Cleanly shutdown runtime during add-on termination.
    pub fn shutdown(&self, py: Python<'_>) -> PyResult<()> {
        let core = Arc::clone(&self.core);
        py.allow_threads(move || core.shutdown())
            .map_err(PyRuntimeError::new_err)
    }

    /// Acknowledge an existing server running on host:port without a process handle.
    #[pyo3(signature = (model_id = None))]
    pub fn adopt(&self, py: Python<'_>, model_id: Option<String>) -> PyResult<RuntimeStatus> {
        let core = Arc::clone(&self.core);
        py.allow_threads(move || core.adopt(model_id.as_deref()))
            .map_err(PyRuntimeError::new_err)
    }
}

#[pymodule]
fn runtime_supervisor(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RuntimeStatus>()?;
    m.add_class::<RuntimeSupervisor>()?;
    Ok(())
}
