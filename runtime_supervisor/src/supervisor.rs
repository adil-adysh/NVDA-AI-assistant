use std::collections::HashMap;
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use crate::health::{HealthChecker, UreqHealthChecker};
use crate::process::{OsProcessDriver, ProcessDriver, ProcessHandle};
use crate::types::{LifecycleState, RuntimeStatus};

#[derive(Debug, Clone, PartialEq, Eq)]
struct ActiveConfig {
    executable: String,
    args: Vec<String>,
    env: HashMap<String, String>,
    startup_identity: String,
}

struct InnerState {
    state: LifecycleState,
    process: Option<Box<dyn ProcessHandle>>,
    generation: u64,
    startup_identity: Option<String>,
    running_model: Option<String>,
    last_error: Option<String>,
    active_config: Option<ActiveConfig>,
}

pub struct SupervisorCore {
    runtime_name: String,
    host: String,
    port: u16,
    base_url: String,
    process_driver: Arc<dyn ProcessDriver>,
    health_checker: Arc<dyn HealthChecker>,
    state: Arc<Mutex<InnerState>>,
    condvar: Arc<Condvar>,
}

impl SupervisorCore {
    pub fn new(runtime_name: String, host: String, port: u16) -> Self {
        Self::with_drivers(
            runtime_name,
            host,
            port,
            Arc::new(OsProcessDriver),
            Arc::new(UreqHealthChecker),
        )
    }

    pub fn with_drivers(
        runtime_name: String,
        host: String,
        port: u16,
        process_driver: Arc<dyn ProcessDriver>,
        health_checker: Arc<dyn HealthChecker>,
    ) -> Self {
        let base_url = if host.contains(':') && !host.starts_with('[') {
            format!("http://[{}]:{}", host, port)
        } else {
            format!("http://{}:{}", host, port)
        };

        let initial_state = InnerState {
            state: LifecycleState::Stopped,
            process: None,
            generation: 0,
            startup_identity: None,
            running_model: None,
            last_error: None,
            active_config: None,
        };

        Self {
            runtime_name,
            host,
            port,
            base_url,
            process_driver,
            health_checker,
            state: Arc::new(Mutex::new(initial_state)),
            condvar: Arc::new(Condvar::new()),
        }
    }

    pub fn runtime_name(&self) -> &str {
        &self.runtime_name
    }

    pub fn host(&self) -> &str {
        &self.host
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    /// Read-only, non-blocking status query.
    pub fn status(&self) -> RuntimeStatus {
        let mut state = self.state.lock().unwrap();
        self.refresh_process_state_locked(&mut state);

        let pid = state.process.as_ref().map(|p| p.pid());
        RuntimeStatus::new(
            state.state,
            pid,
            state.generation,
            state.last_error.clone(),
            state.startup_identity.clone(),
            state.running_model.clone(),
            self.base_url.clone(),
        )
    }

    /// Whether the live owned process matches the specified startup identity.
    pub fn matches_startup_configuration(&self, startup_identity: &str) -> bool {
        let mut state = self.state.lock().unwrap();
        self.refresh_process_state_locked(&mut state);
        state.state == LifecycleState::ReadyOwned
            && state.startup_identity.as_deref() == Some(startup_identity)
    }

    /// Check if child process has exited; update state accordingly.
    fn refresh_process_state_locked(&self, state: &mut InnerState) {
        if state.state == LifecycleState::ReadyOwned || state.state == LifecycleState::Starting {
            if let Some(ref mut process) = state.process {
                match process.poll() {
                    Ok(Some(exit_code)) => {
                        state.process = None;
                        if exit_code != 0 {
                            state.state = LifecycleState::Failed;
                            state.last_error = Some(format!(
                                "{} server process exited unexpectedly with code {}",
                                self.runtime_name, exit_code
                            ));
                        } else {
                            state.state = LifecycleState::Stopped;
                        }
                        self.condvar.notify_all();
                    }
                    Ok(None) => {}
                    Err(e) => {
                        state.last_error = Some(e);
                    }
                }
            }
        }
    }

    /// Ensure the runtime is ready, starting or adopting it if necessary.
    ///
    /// Handles in-flight deduplication: multiple concurrent callers with
    /// the same configuration wait on a single startup sequence.
    #[allow(clippy::too_many_arguments)]
    pub fn ensure_ready(
        &self,
        executable: &str,
        args: &[String],
        env: &HashMap<String, String>,
        startup_identity: &str,
        running_model: Option<&str>,
        timeout: Duration,
    ) -> Result<RuntimeStatus, String> {
        let start_time = Instant::now();

        'outer: loop {
            let mut state = self.state.lock().unwrap();
            self.refresh_process_state_locked(&mut state);

            // 1. ReadyOwned matching current configuration
            if state.state == LifecycleState::ReadyOwned {
                if state.startup_identity.as_deref() == Some(startup_identity) {
                    let pid = state.process.as_ref().map(|p| p.pid());
                    return Ok(RuntimeStatus::new(
                        state.state,
                        pid,
                        state.generation,
                        state.last_error.clone(),
                        state.startup_identity.clone(),
                        state.running_model.clone(),
                        self.base_url.clone(),
                    ));
                }
                // Config changed; restart needed
                drop(state);
                return self.restart(
                    executable,
                    args,
                    env,
                    startup_identity,
                    running_model,
                    timeout.saturating_sub(start_time.elapsed()),
                );
            }

            // 2. ReadyAdopted
            if state.state == LifecycleState::ReadyAdopted {
                drop(state);
                if self
                    .health_checker
                    .check_health(&self.base_url, Duration::from_millis(500))
                {
                    let s = self.state.lock().unwrap();
                    let pid = s.process.as_ref().map(|p| p.pid());
                    return Ok(RuntimeStatus::new(
                        s.state,
                        pid,
                        s.generation,
                        s.last_error.clone(),
                        s.startup_identity.clone(),
                        s.running_model.clone(),
                        self.base_url.clone(),
                    ));
                }
                // Adopted server disappeared; reset to stopped and fall through to spawn
                let mut s = self.state.lock().unwrap();
                s.state = LifecycleState::Stopped;
                continue 'outer;
            }

            // 3. In-flight Starting: deduplicate if matching, supersede if changed
            if state.state == LifecycleState::Starting {
                if let Some(ref active) = state.active_config {
                    if active.startup_identity == startup_identity {
                        // Same config is already starting; wait on condvar
                        let my_gen = state.generation;
                        let remaining = timeout.saturating_sub(start_time.elapsed());
                        if remaining.is_zero() {
                            return Err(format!(
                                "{} server readiness timed out",
                                self.runtime_name
                            ));
                        }
                        let (new_state, _) = self
                            .condvar
                            .wait_timeout_while(state, remaining, |s| {
                                s.state == LifecycleState::Starting && s.generation == my_gen
                            })
                            .unwrap();
                        state = new_state;
                        if state.state == LifecycleState::ReadyOwned
                            || state.state == LifecycleState::ReadyAdopted
                        {
                            let pid = state.process.as_ref().map(|p| p.pid());
                            return Ok(RuntimeStatus::new(
                                state.state,
                                pid,
                                state.generation,
                                state.last_error.clone(),
                                state.startup_identity.clone(),
                                state.running_model.clone(),
                                self.base_url.clone(),
                            ));
                        } else if state.state == LifecycleState::Failed {
                            return Err(state.last_error.clone().unwrap_or_else(|| {
                                format!("{} server failed to start", self.runtime_name)
                            }));
                        }
                        continue 'outer;
                    }
                }
                // Config differs while starting: supersede current startup
                state.generation += 1;
                if let Some(mut old_proc) = state.process.take() {
                    let _ = old_proc.terminate();
                }
            }

            // 4. Stopped or Failed: begin transition to Starting under lock
            state.generation += 1;
            let my_gen = state.generation;
            state.state = LifecycleState::Starting;
            state.last_error = None;
            state.active_config = Some(ActiveConfig {
                executable: executable.to_string(),
                args: args.to_vec(),
                env: env.clone(),
                startup_identity: startup_identity.to_string(),
            });
            self.condvar.notify_all();

            // Check if there is an adoptable server already running
            drop(state);
            if self
                .health_checker
                .check_compatible(&self.base_url, Duration::from_millis(500))
            {
                let mut s = self.state.lock().unwrap();
                if s.generation == my_gen {
                    s.state = LifecycleState::ReadyAdopted;
                    s.running_model = running_model.map(|m| m.to_string());
                    s.last_error = None;
                    s.startup_identity = None;
                    self.condvar.notify_all();
                    return Ok(RuntimeStatus::new(
                        s.state,
                        None,
                        s.generation,
                        None,
                        None,
                        s.running_model.clone(),
                        self.base_url.clone(),
                    ));
                }
                continue 'outer;
            }

            // Spawn child process outside mutex to avoid holding lock across OS syscall
            let spawn_start = Instant::now();
            let spawn_result = self.process_driver.spawn(executable, args, env);

            let mut state = self.state.lock().unwrap();
            // Check if generation changed while spawning (e.g. stop() called)
            if state.generation != my_gen {
                if let Ok(mut child) = spawn_result {
                    let _ = child.terminate();
                }
                if state.state == LifecycleState::Stopped || state.state == LifecycleState::Stopping
                {
                    return Err(format!("{} server startup was stopped", self.runtime_name));
                }
                continue 'outer;
            }

            match spawn_result {
                Err(err) => {
                    state.state = LifecycleState::Failed;
                    state.last_error = Some(err.clone());
                    self.condvar.notify_all();
                    return Err(err);
                }
                Ok(child) => {
                    state.process = Some(child);
                }
            }

            // Poll health loop until ready or timeout
            drop(state);
            let deadline = Instant::now() + timeout.saturating_sub(spawn_start.elapsed());
            let poll_interval = Duration::from_millis(100);

            while Instant::now() < deadline {
                // Check if generation changed or child died
                {
                    let mut s = self.state.lock().unwrap();
                    if s.generation != my_gen {
                        if s.state == LifecycleState::Stopped || s.state == LifecycleState::Stopping
                        {
                            return Err(format!(
                                "{} server startup was stopped",
                                self.runtime_name
                            ));
                        }
                        continue 'outer;
                    }
                    if let Some(ref mut proc) = s.process {
                        if let Ok(Some(code)) = proc.poll() {
                            s.process = None;
                            s.state = LifecycleState::Failed;
                            let err_msg = format!(
                                "{} server process exited unexpectedly with code {}",
                                self.runtime_name, code
                            );
                            s.last_error = Some(err_msg.clone());
                            self.condvar.notify_all();
                            return Err(err_msg);
                        }
                    }
                }

                // Check health
                if self
                    .health_checker
                    .check_health(&self.base_url, Duration::from_millis(200))
                {
                    let mut s = self.state.lock().unwrap();
                    if s.generation == my_gen {
                        s.state = LifecycleState::ReadyOwned;
                        s.startup_identity = Some(startup_identity.to_string());
                        s.running_model = running_model.map(|m| m.to_string());
                        s.last_error = None;
                        self.condvar.notify_all();
                        let pid = s.process.as_ref().map(|p| p.pid());
                        return Ok(RuntimeStatus::new(
                            s.state,
                            pid,
                            s.generation,
                            None,
                            s.startup_identity.clone(),
                            s.running_model.clone(),
                            self.base_url.clone(),
                        ));
                    }
                    if s.state == LifecycleState::Stopped || s.state == LifecycleState::Stopping {
                        return Err(format!("{} server startup was stopped", self.runtime_name));
                    }
                    continue 'outer;
                }

                std::thread::sleep(poll_interval);
            }

            // Readiness timeout expired - check exit one last time before declaring timeout
            let mut s = self.state.lock().unwrap();
            if s.generation == my_gen {
                if let Some(mut proc) = s.process.take() {
                    if let Ok(Some(code)) = proc.poll() {
                        s.state = LifecycleState::Failed;
                        let err_msg = format!(
                            "{} server process exited unexpectedly with code {}",
                            self.runtime_name, code
                        );
                        s.last_error = Some(err_msg.clone());
                        self.condvar.notify_all();
                        return Err(err_msg);
                    }
                    let _ = proc.terminate();
                }
                s.state = LifecycleState::Failed;
                let err_msg = format!(
                    "{} server did not become ready within timeout",
                    self.runtime_name
                );
                s.last_error = Some(err_msg.clone());
                self.condvar.notify_all();
                return Err(err_msg);
            }
            if s.state == LifecycleState::Stopped || s.state == LifecycleState::Stopping {
                return Err(format!("{} server startup was stopped", self.runtime_name));
            }
            continue 'outer;
        }
    }

    /// Stop the server and start it again with fresh configuration.
    #[allow(clippy::too_many_arguments)]
    pub fn restart(
        &self,
        executable: &str,
        args: &[String],
        env: &HashMap<String, String>,
        startup_identity: &str,
        running_model: Option<&str>,
        timeout: Duration,
    ) -> Result<RuntimeStatus, String> {
        let mut state = self.state.lock().unwrap();
        state.generation += 1;
        state.state = LifecycleState::Restarting;
        if let Some(mut proc) = state.process.take() {
            let _ = proc.terminate();
        }
        state.startup_identity = None;
        state.running_model = None;
        self.condvar.notify_all();
        drop(state);

        self.ensure_ready(
            executable,
            args,
            env,
            startup_identity,
            running_model,
            timeout,
        )
    }

    /// Stop the running process and reset to Stopped state.
    pub fn stop(&self, timeout: Duration) -> Result<RuntimeStatus, String> {
        let mut state = self.state.lock().unwrap();
        state.generation += 1;
        state.state = LifecycleState::Stopping;
        let mut proc_opt = state.process.take();
        state.startup_identity = None;
        state.running_model = None;
        self.condvar.notify_all();
        drop(state);

        if let Some(ref mut proc) = proc_opt {
            let _ = proc.terminate();
            let _ = proc.wait_timeout(timeout);
        }

        let mut state = self.state.lock().unwrap();
        state.state = LifecycleState::Stopped;
        self.condvar.notify_all();

        Ok(RuntimeStatus::new(
            state.state,
            None,
            state.generation,
            state.last_error.clone(),
            None,
            None,
            self.base_url.clone(),
        ))
    }

    /// Shutdown the server safely.
    pub fn shutdown(&self) -> Result<(), String> {
        let _ = self.stop(Duration::from_secs(5));
        Ok(())
    }

    /// Explicitly adopt a server running on the endpoint.
    pub fn adopt(&self, model_id: Option<&str>) -> Result<RuntimeStatus, String> {
        let mut state = self.state.lock().unwrap();
        self.refresh_process_state_locked(&mut state);
        if state.state == LifecycleState::ReadyOwned {
            let pid = state.process.as_ref().map(|p| p.pid());
            return Ok(RuntimeStatus::new(
                state.state,
                pid,
                state.generation,
                state.last_error.clone(),
                state.startup_identity.clone(),
                state.running_model.clone(),
                self.base_url.clone(),
            ));
        }

        drop(state);
        if self
            .health_checker
            .check_compatible(&self.base_url, Duration::from_secs(2))
        {
            let mut s = self.state.lock().unwrap();
            s.generation += 1;
            s.state = LifecycleState::ReadyAdopted;
            s.running_model = model_id.map(|m| m.to_string());
            s.startup_identity = None;
            s.last_error = None;
            self.condvar.notify_all();
            return Ok(RuntimeStatus::new(
                s.state,
                None,
                s.generation,
                None,
                None,
                s.running_model.clone(),
                self.base_url.clone(),
            ));
        }

        Err(format!(
            "No compatible {} server responding at {}",
            self.runtime_name, self.base_url
        ))
    }
}
