use std::collections::HashMap;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

pub trait ProcessHandle: Send + Sync {
    fn pid(&self) -> u32;
    fn poll(&mut self) -> Result<Option<i32>, String>;
    fn terminate(&mut self) -> Result<(), String>;
    fn wait_timeout(&mut self, timeout: Duration) -> Result<Option<i32>, String>;
}

pub trait ProcessDriver: Send + Sync {
    fn spawn(
        &self,
        executable: &str,
        args: &[String],
        env: &HashMap<String, String>,
    ) -> Result<Box<dyn ProcessHandle>, String>;
}

pub struct OsProcessDriver;

impl ProcessDriver for OsProcessDriver {
    fn spawn(
        &self,
        executable: &str,
        args: &[String],
        env: &HashMap<String, String>,
    ) -> Result<Box<dyn ProcessHandle>, String> {
        let mut cmd = Command::new(executable);
        cmd.args(args);
        for (k, v) in env {
            cmd.env(k, v);
        }
        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);

        cmd.stdout(Stdio::null());
        cmd.stderr(Stdio::null());

        let child = cmd
            .spawn()
            .map_err(|e| format!("Failed to spawn process '{}': {}", executable, e))?;

        Ok(Box::new(OsProcessHandle {
            pid: child.id(),
            child,
        }))
    }
}

pub struct OsProcessHandle {
    pid: u32,
    child: Child,
}

impl ProcessHandle for OsProcessHandle {
    fn pid(&self) -> u32 {
        self.pid
    }

    fn poll(&mut self) -> Result<Option<i32>, String> {
        match self.child.try_wait() {
            Ok(Some(status)) => Ok(Some(status.code().unwrap_or(-1))),
            Ok(None) => Ok(None),
            Err(e) => Err(format!("Failed to poll process {}: {}", self.pid, e)),
        }
    }

    fn terminate(&mut self) -> Result<(), String> {
        // Under Windows, kill() invokes TerminateProcess, matching Python Popen.terminate()
        let _ = self.child.kill();
        Ok(())
    }

    fn wait_timeout(&mut self, timeout: Duration) -> Result<Option<i32>, String> {
        let start = Instant::now();
        loop {
            if let Some(code) = self.poll()? {
                return Ok(Some(code));
            }
            if start.elapsed() >= timeout {
                // Timeout reached; force terminate
                let _ = self.terminate();
                let _ = self.child.wait();
                return Ok(None);
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }
}
