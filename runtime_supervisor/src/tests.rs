use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicI32, AtomicUsize, Ordering};
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
}

impl ProcessHandle for FakeProcessHandle {
    fn pid(&self) -> u32 {
        self.pid
    }

    fn poll(&mut self) -> Result<Option<i32>, String> {
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
        self.alive.store(false, Ordering::SeqCst);
        Ok(Some(self.exit_code.load(Ordering::SeqCst)))
    }
}

struct FakeProcessDriver {
    spawns: Arc<AtomicUsize>,
    fail_spawn: Arc<AtomicBool>,
    exit_immediately: Arc<AtomicBool>,
    exit_code: Arc<AtomicI32>,
    current_alive: Arc<AtomicBool>,
}

impl FakeProcessDriver {
    fn new() -> Self {
        Self {
            spawns: Arc::new(AtomicUsize::new(0)),
            fail_spawn: Arc::new(AtomicBool::new(false)),
            exit_immediately: Arc::new(AtomicBool::new(false)),
            exit_code: Arc::new(AtomicI32::new(1)),
            current_alive: Arc::new(AtomicBool::new(true)),
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
        }))
    }
}

struct FakeHealthChecker {
    healthy: Arc<AtomicBool>,
    compatible: Arc<AtomicBool>,
    checks: Arc<AtomicUsize>,
    become_healthy_after: Arc<AtomicUsize>,
}

impl FakeHealthChecker {
    fn new(healthy: bool, compatible: bool) -> Self {
        Self {
            healthy: Arc::new(AtomicBool::new(healthy)),
            compatible: Arc::new(AtomicBool::new(compatible)),
            checks: Arc::new(AtomicUsize::new(0)),
            become_healthy_after: Arc::new(AtomicUsize::new(0)),
        }
    }
}

impl HealthChecker for FakeHealthChecker {
    fn check_health(&self, _base_url: &str, _timeout: Duration) -> bool {
        let count = self.checks.fetch_add(1, Ordering::SeqCst);
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
