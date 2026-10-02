use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

/// Explicit lifecycle states of a managed runtime.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LifecycleState {
    Stopped,
    Starting,
    ReadyOwned,
    ReadyAdopted,
    Restarting,
    Stopping,
    Failed,
}

impl LifecycleState {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Stopped => "stopped",
            Self::Starting => "starting",
            Self::ReadyOwned => "ready_owned",
            Self::ReadyAdopted => "ready_adopted",
            Self::Restarting => "restarting",
            Self::Stopping => "stopping",
            Self::Failed => "failed",
        }
    }

    pub fn is_ready(&self) -> bool {
        matches!(self, Self::ReadyOwned | Self::ReadyAdopted)
    }

    pub fn is_running(&self) -> bool {
        matches!(self, Self::ReadyOwned)
    }

    pub fn is_adopted(&self) -> bool {
        matches!(self, Self::ReadyAdopted)
    }
}

/// Immutable snapshot of the runtime supervisor's state.
///
/// Safe to query from any thread (including NVDA's main thread) as it
/// performs no I/O, socket communication, or blocking waits.
#[pyclass(frozen)]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeStatus {
    #[pyo3(get)]
    pub state: String,
    #[pyo3(get)]
    pub is_ready: bool,
    #[pyo3(get)]
    pub is_running: bool,
    #[pyo3(get)]
    pub is_adopted: bool,
    #[pyo3(get)]
    pub pid: Option<u32>,
    #[pyo3(get)]
    pub generation: u64,
    #[pyo3(get)]
    pub error_message: Option<String>,
    #[pyo3(get)]
    pub startup_identity: Option<String>,
    #[pyo3(get)]
    pub running_model: Option<String>,
    #[pyo3(get)]
    pub base_url: String,
}

#[pymethods]
impl RuntimeStatus {
    fn __repr__(&self) -> String {
        format!(
            "RuntimeStatus(state='{}', ready={}, running={}, adopted={}, pid={:?}, gen={}, error={:?})",
            self.state, self.is_ready, self.is_running, self.is_adopted, self.pid, self.generation, self.error_message
        )
    }

    fn __str__(&self) -> String {
        self.__repr__()
    }
}

impl RuntimeStatus {
    pub fn new(
        state: LifecycleState,
        pid: Option<u32>,
        generation: u64,
        error_message: Option<String>,
        startup_identity: Option<String>,
        running_model: Option<String>,
        base_url: String,
    ) -> Self {
        Self {
            state: state.as_str().to_string(),
            is_ready: state.is_ready(),
            is_running: pid.is_some() && state == LifecycleState::ReadyOwned,
            is_adopted: state.is_adopted(),
            pid,
            generation,
            error_message,
            startup_identity,
            running_model,
            base_url,
        }
    }
}
