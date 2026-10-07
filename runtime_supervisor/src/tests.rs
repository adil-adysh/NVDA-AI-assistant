use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use crate::health::HealthChecker;
use crate::process::{ProcessDriver, ProcessHandle};
use crate::supervisor::SupervisorCore;

struct FakeProcessHandle {
    pid: u32,
    alive: Arc<AtomicBool>,
    exit_code: Arc<AtomicI32>,
    poll_error: Arc<AtomicBool>,
    wait_delay_ms: Arc<AtomicU64>,
    wait_called: Arc<AtomicBool>,
    wait_completed: Arc<AtomicBool>,
}

impl ProcessHandle for FakeProcessHandle {
    fn pid(&self) -> u32 {
        self.pid
    }

    fn poll(&mut self) -> Result<Option<i32>, String> {
        if self.poll_error.load(Ordering::SeqCst) {
            return Err("Simulated process polling error".to_string());
        }
        if self.alive.load(Ordering::SeqCst) {
            Ok(None)
        } else {
            Ok(Some(self.exit_code.load(Ordering::SeqCst)))
        }
    }

    fn terminate(&mut self) -> Result<(), String> {
        self.alive.store(false, Ordering::SeqCst);
        Ok(())
    }

    fn wait_timeout(&mut self, _timeout: Duration) -> Result<Option<i32>, String> {
        self.wait_called.store(true, Ordering::SeqCst);
        let delay = self.wait_delay_ms.load(Ordering::SeqCst);
        if delay > 0 {
            thread::sleep(Duration::from_millis(delay));
        }
        self.alive.store(false, Ordering::SeqCst);
        self.wait_completed.store(true, Ordering::SeqCst);
        Ok(Some(self.exit_code.load(Ordering::SeqCst)))
    }
}

struct FakeProcessDriver {
    spawns: Arc<AtomicUsize>,
    fail_spawn: Arc<AtomicBool>,
    exit_immediately: Arc<AtomicBool>,
    exit_code: Arc<AtomicI32>,
    current_alive: Arc<AtomicBool>,
    poll_error: Arc<AtomicBool>,
    wait_delay_ms: Arc<AtomicU64>,
    last_wait_called: Arc<AtomicBool>,
    last_wait_completed: Arc<AtomicBool>,
    spawn_delay_ms: Arc<AtomicU64>,
}

impl FakeProcessDriver {
    fn new() -> Self {
        Self {
            spawns: Arc::new(AtomicUsize::new(0)),
            fail_spawn: Arc::new(AtomicBool::new(false)),
            exit_immediately: Arc::new(AtomicBool::new(false)),
            exit_code: Arc::new(AtomicI32::new(1)),
            current_alive: Arc::new(AtomicBool::new(true)),
            poll_error: Arc::new(AtomicBool::new(false)),
            wait_delay_ms: Arc::new(AtomicU64::new(0)),
            last_wait_called: Arc::new(AtomicBool::new(false)),
            last_wait_completed: Arc::new(AtomicBool::new(false)),
            spawn_delay_ms: Arc::new(AtomicU64::new(0)),
        }
    }
}

impl ProcessDriver for FakeProcessDriver {
    fn spawn(
        &self,
        _executable: &str,
        _args: &[String],
        _env: &HashMap<String, String>,
    ) -> Result<Box<dyn ProcessHandle>, String> {
        let delay = self.spawn_delay_ms.load(Ordering::SeqCst);
        if delay > 0 {
            thread::sleep(Duration::from_millis(delay));
        }
        let count = self.spawns.fetch_add(1, Ordering::SeqCst);
        if self.fail_spawn.load(Ordering::SeqCst) {
            return Err("Controlled spawn failure".to_string());
        }
        let alive = if self.exit_immediately.load(Ordering::SeqCst) {
            Arc::new(AtomicBool::new(false))
        } else {
            self.current_alive.store(true, Ordering::SeqCst);
            Arc::clone(&self.current_alive)
        };

        Ok(Box::new(FakeProcessHandle {
            pid: 1000 + count as u32,
            alive,
            exit_code: Arc::clone(&self.exit_code),
            poll_error: Arc::clone(&self.poll_error),
            wait_delay_ms: Arc::clone(&self.wait_delay_ms),
            wait_called: Arc::clone(&self.last_wait_called),
            wait_completed: Arc::clone(&self.last_wait_completed),
        }))
    }
}

struct FakeHealthChecker {
    healthy: Arc<AtomicBool>,
    compatible: Arc<AtomicBool>,
    checks: Arc<AtomicUsize>,
    become_healthy_after: Arc<AtomicUsize>,
    become_unhealthy_after: Arc<AtomicUsize>,
}

impl FakeHealthChecker {
    fn new(healthy: bool, compatible: bool) -> Self {
        Self {
            healthy: Arc::new(AtomicBool::new(healthy)),
            compatible: Arc::new(AtomicBool::new(compatible)),
            checks: Arc::new(AtomicUsize::new(0)),
            become_healthy_after: Arc::new(AtomicUsize::new(0)),
            become_unhealthy_after: Arc::new(AtomicUsize::new(0)),
        }
    }
}

impl HealthChecker for FakeHealthChecker {
    fn check_health(&self, _base_url: &str, _timeout: Duration) -> bool {
        let count = self.checks.fetch_add(1, Ordering::SeqCst);
        let unh_threshold = self.become_unhealthy_after.load(Ordering::SeqCst);
        if unh_threshold > 0 && count >= unh_threshold {
            return false;
        }
        let threshold = self.become_healthy_after.load(Ordering::SeqCst);
        if threshold > 0 && count >= threshold {
            return true;
        }
        self.healthy.load(Ordering::SeqCst)
    }

    fn check_compatible(&self, _base_url: &str, _timeout: Duration) -> bool {
        self.compatible.load(Ordering::SeqCst)
    }
}

fn create_test_supervisor(
    driver: Arc<FakeProcessDriver>,
    health: Arc<FakeHealthChecker>,
) -> SupervisorCore {
    SupervisorCore::with_drivers(
        "litert-lm".to_string(),
        "127.0.0.1".to_string(),
        9379,
        driver,
        health,
    )
}

#[test]
fn test_simultaneous_ensure_ready_calls_deduplicate() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(false, false));
    health.become_healthy_after.store(2, Ordering::SeqCst);
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    let threads: Vec<_> = (0..5)
        .map(|_| {
            let sup = Arc::clone(&supervisor);
            thread::spawn(move || {
                sup.ensure_ready(
                    "python.exe",
                    &["serve".into()],
                    &HashMap::new(),
                    "config-v1",
                    None,
                    Duration::from_secs(3),
                )
            })
        })
        .collect();

    for t in threads {
        let res = t.join().unwrap();
        assert!(res.is_ok(), "ensure_ready failed: {:?}", res);
    }

    // Only one process spawned despite 5 concurrent callers
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);
    let status = supervisor.status();
    assert_eq!(status.state, "ready_owned");
    assert!(status.is_ready);
    assert!(status.is_running);
}

#[test]
fn test_child_exits_immediately_after_spawn() {
    let driver = Arc::new(FakeProcessDriver::new());
    driver.exit_immediately.store(true, Ordering::SeqCst);
    driver.exit_code.store(42, Ordering::SeqCst);

    let health = Arc::new(FakeHealthChecker::new(false, false));
    let supervisor = create_test_supervisor(driver, health);

    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );

    assert!(res.is_err());
    let err = res.unwrap_err();
    assert!(err.contains("code 42"), "unexpected error: {}", err);

    let status = supervisor.status();
    assert_eq!(status.state, "failed");
    assert!(!status.is_ready);
}

#[test]
fn test_child_exits_after_becoming_ready() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = create_test_supervisor(Arc::clone(&driver), health);

    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res.is_ok());
    assert_eq!(supervisor.status().state, "ready_owned");

    // Simulate process crash
    driver.current_alive.store(false, Ordering::SeqCst);
    driver.exit_code.store(137, Ordering::SeqCst);

    // Calling status() detects crash non-blockingly
    let status = supervisor.status();
    assert_eq!(status.state, "failed");
    assert!(!status.is_running);
    assert!(status.error_message.unwrap().contains("137"));
}

#[test]
fn test_config_change_restarts_running_server() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = create_test_supervisor(Arc::clone(&driver), health);

    // Initial startup with config-v1
    let res1 = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res1.is_ok());
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);

    // Same config: no new spawn
    let res2 = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res2.is_ok());
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);

    // Changed config-v2: restarts with fresh spawn
    let res3 = supervisor.ensure_ready(
        "python.exe",
        &["serve".into(), "--new-arg".into()],
        &HashMap::new(),
        "config-v2",
        None,
        Duration::from_secs(1),
    );
    assert!(res3.is_ok());
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 2);
    assert_eq!(
        supervisor.status().startup_identity.as_deref(),
        Some("config-v2")
    );
}

#[test]
fn test_adopted_server_detected_and_reused() {
    let driver = Arc::new(FakeProcessDriver::new());
    // Endpoint is already compatible and healthy
    let health = Arc::new(FakeHealthChecker::new(true, true));
    let supervisor = create_test_supervisor(Arc::clone(&driver), health);

    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res.is_ok());
    // No new process spawned because endpoint was adopted
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 0);
    let status = supervisor.status();
    assert_eq!(status.state, "ready_adopted");
    assert!(status.is_ready);
    assert!(status.is_adopted);
    assert!(!status.is_running);
}

#[test]
fn test_adopted_server_disappears_triggers_spawn() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, true));
    let supervisor = create_test_supervisor(Arc::clone(&driver), Arc::clone(&health));

    // Initially adopted
    supervisor
        .ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v1",
            None,
            Duration::from_secs(1),
        )
        .unwrap();
    assert_eq!(supervisor.status().state, "ready_adopted");

    // Adopted server disappears (endpoint dies)
    health.healthy.store(false, Ordering::SeqCst);
    health.compatible.store(false, Ordering::SeqCst);
    // Next check will fail, causing spawn; make subsequent health check succeed for newly spawned child
    health.become_healthy_after.store(1, Ordering::SeqCst);

    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(2),
    );
    assert!(res.is_ok());
    // A real child process was spawned to replace the dead adopted server
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);
    assert_eq!(supervisor.status().state, "ready_owned");
}

#[test]
fn test_stop_during_startup_cancels_cleanly() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(false, false));
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    let sup_clone = Arc::clone(&supervisor);
    let starter = thread::spawn(move || {
        sup_clone.ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v1",
            None,
            Duration::from_secs(3),
        )
    });

    // Wait until supervisor enters Starting
    while supervisor.status().state != "starting" {
        thread::sleep(Duration::from_millis(10));
    }

    // Call stop during startup
    supervisor.stop(Duration::from_millis(100)).unwrap();

    let _ = starter.join();
    let status = supervisor.status();
    assert_eq!(status.state, "stopped");
    assert!(!status.is_ready);
}

#[test]
fn test_stale_generation_does_not_overwrite_newer_state() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    // Start with config-v1
    supervisor
        .ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v1",
            None,
            Duration::from_secs(1),
        )
        .unwrap();
    assert_eq!(
        supervisor.status().startup_identity.as_deref(),
        Some("config-v1")
    );

    // Restart with config-v2
    supervisor
        .restart(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v2",
            None,
            Duration::from_secs(1),
        )
        .unwrap();
    let status = supervisor.status();
    assert_eq!(status.startup_identity.as_deref(), Some("config-v2"));
    assert_eq!(status.generation, 3);
}

#[test]
fn test_wrong_unrelated_server_on_endpoint_is_not_adopted() {
    let driver = Arc::new(FakeProcessDriver::new());
    // Endpoint returns 200 for health but compatible returns false (e.g. non-LLM server)
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = create_test_supervisor(Arc::clone(&driver), health);

    // ensure_ready must NOT adopt incompatible server; must spawn owned runtime
    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res.is_ok());
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);
    assert_eq!(supervisor.status().state, "ready_owned");
}

#[test]
fn test_os_process_driver_exit_code() {
    use crate::process::OsProcessDriver;
    let driver = OsProcessDriver;
    let mut handle = driver
        .spawn("cmd.exe", &["/C".into(), "exit 42".into()], &HashMap::new())
        .unwrap();
    std::thread::sleep(Duration::from_millis(200));
    let code = handle.poll().unwrap();
    assert_eq!(code, Some(42));
}

#[test]
fn test_ensure_ready_with_os_process_child_exit() {
    let supervisor = SupervisorCore::new("litert-lm".into(), "127.0.0.1".into(), 9991);
    let res = supervisor.ensure_ready(
        "cmd.exe",
        &["/C".into(), "exit 42".into()],
        &HashMap::new(),
        "ident-1",
        None,
        Duration::from_secs(3),
    );
    assert!(res.is_err());
    let err = res.unwrap_err();
    assert!(err.contains("code 42"), "unexpected error: {}", err);
}

#[test]
fn test_child_crash_increments_generation_monotonically() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = create_test_supervisor(Arc::clone(&driver), health);

    // Initial startup to ReadyOwned
    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res.is_ok());
    let initial_status = supervisor.status();
    assert_eq!(initial_status.state, "ready_owned");
    let gen_ready = initial_status.generation;
    assert!(gen_ready >= 1);

    // Simulate child process crash (e.g. exit code 137 / SIGKILL)
    driver.current_alive.store(false, Ordering::SeqCst);
    driver.exit_code.store(137, Ordering::SeqCst);

    // Non-blocking status query triggers refresh_process_state_locked
    let status = supervisor.status();
    assert_eq!(status.state, "failed");
    assert!(!status.is_running);
    assert!(!status.is_ready);
    assert_eq!(
        status.generation,
        gen_ready + 1,
        "Generation must increment monotonically when child process crashes"
    );
    assert!(
        status.error_message.as_ref().unwrap().contains("137"),
        "Error message should mention exit code 137"
    );

    // Subsequent status calls must remain stable and not re-increment indefinitely
    let status2 = supervisor.status();
    assert_eq!(status2.state, "failed");
    assert_eq!(status2.generation, status.generation);
}

#[test]
fn test_startup_child_crash_increments_generation() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(false, false));
    health.become_healthy_after.store(50, Ordering::SeqCst);
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    // Spawn thread to simulate child crash 50ms into startup
    let driver_clone = Arc::clone(&driver);
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(50));
        driver_clone.current_alive.store(false, Ordering::SeqCst);
        driver_clone.exit_code.store(42, Ordering::SeqCst);
    });

    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(2),
    );

    assert!(res.is_err());
    let err = res.unwrap_err();
    assert!(err.contains("code 42"), "Unexpected error: {}", err);

    let status = supervisor.status();
    assert_eq!(status.state, "failed");
    assert!(!status.is_ready);
    assert!(
        status.generation >= 2,
        "Generation must increment on startup crash detection, got {}",
        status.generation
    );
}

#[test]
fn test_startup_readiness_timeout_increments_generation() {
    let driver = Arc::new(FakeProcessDriver::new());
    // Health checker never succeeds
    let health = Arc::new(FakeHealthChecker::new(false, false));
    let supervisor = create_test_supervisor(Arc::clone(&driver), health);

    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_millis(200),
    );

    assert!(res.is_err());
    let err = res.unwrap_err();
    assert!(
        err.contains("did not become ready within timeout"),
        "Unexpected error: {}",
        err
    );

    let status = supervisor.status();
    assert_eq!(status.state, "failed");
    assert!(!status.is_ready);
    assert!(!status.is_running);
    assert!(
        status.generation >= 2,
        "Generation must increment on readiness timeout, got {}",
        status.generation
    );
}

#[test]
fn test_ensure_ready_blocks_and_waits_if_stopping() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    // 1. Initial startup
    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res.is_ok());
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);

    // 2. Configure fake process to delay 150ms during wait_timeout in stop()
    driver.wait_delay_ms.store(150, Ordering::SeqCst);

    // 3. Thread A initiates stop()
    let sup_a = Arc::clone(&supervisor);
    let stop_thread = thread::spawn(move || {
        sup_a.stop(Duration::from_millis(500))
    });

    // Wait until supervisor enters Stopping state
    while supervisor.status().state != "stopping" {
        thread::sleep(Duration::from_millis(5));
    }

    // 4. Thread B calls ensure_ready while state is Stopping
    let sup_b = Arc::clone(&supervisor);
    let ensure_ready_thread = thread::spawn(move || {
        sup_b.ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v1",
            None,
            Duration::from_secs(2),
        )
    });

    // 5. Join stop thread; must complete cleanly
    let stop_res = stop_thread.join().unwrap();
    assert!(stop_res.is_ok());

    // 6. Join ensure_ready thread; must complete cleanly and not be aborted or overwritten
    let ready_res = ensure_ready_thread.join().unwrap();
    assert!(ready_res.is_ok(), "ensure_ready failed: {:?}", ready_res);

    // 7. Verify supervisor final state is ReadyOwned
    let final_status = supervisor.status();
    assert_eq!(final_status.state, "ready_owned");
    assert!(final_status.is_ready);
    assert!(final_status.is_running);

    // 8. Exactly 2 spawns: original process (1) + replacement after stop (2)
    assert_eq!(
        driver.spawns.load(Ordering::SeqCst),
        2,
        "Exactly 2 processes should have been spawned (no orphaned or duplicate processes)"
    );
}

#[test]
fn test_stop_generation_guard_preserves_concurrent_epoch() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    // Initial startup to ReadyOwned (gen 1)
    supervisor
        .ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v1",
            None,
            Duration::from_secs(1),
        )
        .unwrap();

    driver.wait_delay_ms.store(120, Ordering::SeqCst);

    let sup_clone = Arc::clone(&supervisor);
    let stop_thread = thread::spawn(move || {
        sup_clone.stop(Duration::from_millis(500))
    });

    while supervisor.status().state != "stopping" {
        thread::sleep(Duration::from_millis(5));
    }

    // Thread B calls ensure_ready with fresh config-v2
    let sup_clone2 = Arc::clone(&supervisor);
    let start_thread = thread::spawn(move || {
        sup_clone2.ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v2",
            None,
            Duration::from_secs(2),
        )
    });

    let stop_res = stop_thread.join().unwrap();
    assert!(stop_res.is_ok());

    let start_res = start_thread.join().unwrap();
    assert!(start_res.is_ok());

    let final_status = supervisor.status();
    // Must remain ReadyOwned with config-v2, NOT overwritten by stop() to Stopped
    assert_eq!(final_status.state, "ready_owned");
    assert_eq!(final_status.startup_identity.as_deref(), Some("config-v2"));
    assert!(final_status.generation >= 3);
}

#[test]
fn test_restart_waits_for_child_process_termination() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = create_test_supervisor(Arc::clone(&driver), health);

    // Initial startup
    let res = supervisor.ensure_ready(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v1",
        None,
        Duration::from_secs(1),
    );
    assert!(res.is_ok());
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);

    // Configure wait_delay_ms so that wait_timeout takes 50ms
    driver.wait_delay_ms.store(50, Ordering::SeqCst);

    // Restart with config-v2
    let restart_res = supervisor.restart(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v2",
        None,
        Duration::from_secs(2),
    );
    assert!(restart_res.is_ok());

    // Assert that wait_timeout was called and completed on the old process handle
    assert!(
        driver.last_wait_called.load(Ordering::SeqCst),
        "restart() must invoke wait_timeout on the terminating process handle"
    );
    assert!(
        driver.last_wait_completed.load(Ordering::SeqCst),
        "restart() must wait for child process termination before completing"
    );
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 2);
    assert_eq!(
        supervisor.status().startup_identity.as_deref(),
        Some("config-v2")
    );
}

#[test]
fn test_restart_does_not_adopt_dying_server() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = create_test_supervisor(Arc::clone(&driver), Arc::clone(&health));

    // Initial startup
    supervisor
        .ensure_ready(
            "python.exe",
            &["serve".into()],
            &HashMap::new(),
            "config-v1",
            None,
            Duration::from_secs(1),
        )
        .unwrap();
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);

    // On restart, health checker must not trick supervisor into adopting dying server.
    health.compatible.store(false, Ordering::SeqCst);

    let res = supervisor.restart(
        "python.exe",
        &["serve".into()],
        &HashMap::new(),
        "config-v2",
        None,
        Duration::from_secs(2),
    );
    assert!(res.is_ok());

    let status = supervisor.status();
    assert_eq!(status.state, "ready_owned");
    assert!(!status.is_adopted);
    assert!(status.is_running);
    assert_eq!(driver.spawns.load(Ordering::SeqCst), 2);
}

#[test]
fn test_concurrent_ensure_ready_differing_configs_no_livelock() {
    let driver = Arc::new(FakeProcessDriver::new());
    let health = Arc::new(FakeHealthChecker::new(true, false));
    let supervisor = Arc::new(create_test_supervisor(Arc::clone(&driver), health));

    // Spawn 2 threads concurrently with differing configurations
    let sup1 = Arc::clone(&supervisor);
    let t1 = thread::spawn(move || {
        sup1.ensure_ready(
            "python.exe",
            &["serve".into(), "--model=A".into()],
            &HashMap::new(),
            "config-model-A",
            Some("model-A"),
            Duration::from_secs(3),
        )
    });

    let sup2 = Arc::clone(&supervisor);
    let t2 = thread::spawn(move || {
        sup2.ensure_ready(
            "python.exe",
            &["serve".into(), "--model=B".into()],
            &HashMap::new(),
            "config-model-B",
            Some("model-B"),
            Duration::from_secs(3),
        )
    });

    let res1 = t1.join().unwrap();
    let res2 = t2.join().unwrap();

    assert!(res1.is_ok(), "Thread 1 failed: {:?}", res1);
    assert!(res2.is_ok(), "Thread 2 failed: {:?}", res2);

    let spawn_count = driver.spawns.load(Ordering::SeqCst);
    // In a ping-pong livelock, spawn_count would be large (> 10 or timeout).
    // With condvar coordination, spawn_count is strictly bounded (at most 2).
    assert!(
        spawn_count <= 2,
        "Livelock detected: expected <= 2 spawns, got {}",
        spawn_count
    );

    let final_status = supervisor.status();
    assert_eq!(final_status.state, "ready_owned");
    assert!(final_status.is_ready);
    assert!(
        final_status.startup_identity.as_deref() == Some("config-model-A")
            || final_status.startup_identity.as_deref() == Some("config-model-B")
    );
}

#[cfg(windows)]
#[test]
fn test_os_process_handle_job_object_containment() {
    use crate::process::OsProcessDriver;

    let driver = OsProcessDriver;
    // Spawn a benign Windows process that runs for several seconds
    let mut handle = driver
        .spawn(
            "cmd.exe",
            &["/C".into(), "ping".into(), "127.0.0.1".into(), "-n".into(), "4".into()],
            &HashMap::new(),
        )
        .expect("Failed to spawn OS test process");

    let pid = handle.pid();
    assert!(pid > 0);

    // Verify the process is assigned to a Windows Job Object using Win32 API
    unsafe {
        #[link(name = "kernel32")]
        extern "system" {
            fn OpenProcess(dwDesiredAccess: u32, bInheritHandle: i32, dwProcessId: u32) -> *mut std::ffi::c_void;
            fn IsProcessInJob(hProcess: *mut std::ffi::c_void, hJob: *mut std::ffi::c_void, lpResult: *mut i32) -> i32;
            fn CloseHandle(hObject: *mut std::ffi::c_void) -> i32;
        }

        const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
        let h_proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        assert!(
            !h_proc.is_null(),
            "Failed to open process handle for PID {}",
            pid
        );

        let mut in_job: i32 = 0;
        let success = IsProcessInJob(h_proc, std::ptr::null_mut(), &mut in_job);
        CloseHandle(h_proc);

        assert_ne!(success, 0, "IsProcessInJob Win32 call failed");
        assert_ne!(
            in_job, 0,
            "Spawned process (PID {}) is NOT contained in a Windows Job Object",
            pid
        );
    }

    // Clean up
    let _ = handle.terminate();
}
