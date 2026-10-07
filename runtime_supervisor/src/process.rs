use std::collections::HashMap;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[cfg(windows)]
#[allow(non_snake_case, non_camel_case_types, non_upper_case_globals)]
mod win32 {
    use std::ffi::c_void;

    pub type HANDLE = *mut c_void;
    pub type BOOL = i32;
    pub type DWORD = u32;

    pub const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: DWORD = 0x00002000;
    pub const JobObjectExtendedLimitInformation: i32 = 9;

    #[repr(C)]
    #[derive(Debug, Default, Copy, Clone)]
    pub struct IO_COUNTERS {
        pub read_operation_count: u64,
        pub write_operation_count: u64,
        pub other_operation_count: u64,
        pub read_transfer_count: u64,
        pub write_transfer_count: u64,
        pub other_transfer_count: u64,
    }

    #[repr(C)]
    #[derive(Debug, Default, Copy, Clone)]
    pub struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        pub per_process_user_time_limit: i64,
        pub per_job_user_time_limit: i64,
        pub limit_flags: DWORD,
        pub minimum_working_set_size: usize,
        pub maximum_working_set_size: usize,
        pub active_process_limit: DWORD,
        pub affinity: usize,
        pub priority_class: DWORD,
        pub scheduling_class: DWORD,
    }

    #[repr(C)]
    #[derive(Debug, Default, Copy, Clone)]
    pub struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        pub basic_limit_information: JOBOBJECT_BASIC_LIMIT_INFORMATION,
        pub io_info: IO_COUNTERS,
        pub process_memory_limit: usize,
        pub job_memory_limit: usize,
        pub peak_process_memory_limit: usize,
        pub peak_job_memory_limit: usize,
    }

    extern "system" {
        pub fn CreateJobObjectW(lp_job_attributes: *mut c_void, lp_name: *const u16) -> HANDLE;
        pub fn SetInformationJobObject(
            h_job: HANDLE,
            job_object_info_class: i32,
            lp_job_object_info: *const c_void,
            cb_job_object_info_length: DWORD,
        ) -> BOOL;
        pub fn AssignProcessToJobObject(h_job: HANDLE, h_process: HANDLE) -> BOOL;
        pub fn CloseHandle(h_object: HANDLE) -> BOOL;
        pub fn GetLastError() -> DWORD;
    }
}

#[cfg(windows)]
pub struct JobHandle(win32::HANDLE);

#[cfg(windows)]
unsafe impl Send for JobHandle {}
#[cfg(windows)]
unsafe impl Sync for JobHandle {}

#[cfg(windows)]
impl JobHandle {
    pub fn create_kill_on_close() -> Result<Self, String> {
        unsafe {
            let handle = win32::CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
            if handle.is_null() {
                let err = win32::GetLastError();
                return Err(format!("CreateJobObjectW failed with error code {}", err));
            }

            let mut info = win32::JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
            info.basic_limit_information.limit_flags = win32::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

            let ok = win32::SetInformationJobObject(
                handle,
                win32::JobObjectExtendedLimitInformation,
                &info as *const _ as *const std::ffi::c_void,
                std::mem::size_of::<win32::JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as win32::DWORD,
            );

            if ok == 0 {
                let err = win32::GetLastError();
                win32::CloseHandle(handle);
                return Err(format!("SetInformationJobObject failed with error code {}", err));
            }

            Ok(Self(handle))
        }
    }

    pub fn assign_process(&self, process_handle: win32::HANDLE) -> Result<(), String> {
        unsafe {
            let ok = win32::AssignProcessToJobObject(self.0, process_handle);
            if ok == 0 {
                let err = win32::GetLastError();
                return Err(format!("AssignProcessToJobObject failed with error code {}", err));
            }
            Ok(())
        }
    }

    pub fn raw_handle(&self) -> win32::HANDLE {
        self.0
    }
}

#[cfg(windows)]
impl Drop for JobHandle {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                win32::CloseHandle(self.0);
            }
            self.0 = std::ptr::null_mut();
        }
    }
}

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

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("Failed to spawn process '{}': {}", executable, e))?;

        #[cfg(windows)]
        let job = {
            use std::os::windows::io::AsRawHandle;
            match JobHandle::create_kill_on_close() {
                Ok(j) => {
                    if let Err(e) = j.assign_process(child.as_raw_handle() as win32::HANDLE) {
                        let _ = child.kill();
                        let _ = child.wait();
                        return Err(format!("Failed to bind child process to Job Object: {}", e));
                    }
                    Some(j)
                }
                Err(e) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!("Failed to create Job Object with KILL_ON_JOB_CLOSE: {}", e));
                }
            }
        };

        Ok(Box::new(OsProcessHandle {
            pid: child.id(),
            child,
            #[cfg(windows)]
            _job: job,
        }))
    }
}

pub struct OsProcessHandle {
    pid: u32,
    child: Child,
    #[cfg(windows)]
    _job: Option<JobHandle>,
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
