use std::ffi::{c_void, OsStr};
use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::{FromRawHandle, RawHandle};
use std::ptr::null_mut;
use std::thread;
use std::time::Duration;

use windows::core::{PCWSTR, Result};
use windows::Win32::Foundation::{GetLastError, HANDLE, INVALID_HANDLE_VALUE};

use crate::app;
use crate::protocol::HostResponse;

const PIPE_NAME: &str = r"\\.\pipe\nvda_ai_assistant_ui";
const BUFFER_SIZE: u32 = 4096;
const PIPE_ACCESS_DUPLEX: u32 = 0x00000003;
const PIPE_TYPE_MESSAGE: u32 = 0x00000004;
const PIPE_READMODE_MESSAGE: u32 = 0x00000002;
const PIPE_WAIT: u32 = 0x00000000;
const PIPE_UNLIMITED_INSTANCES: u32 = 255;
const FILE_FLAG_FIRST_PIPE_INSTANCE: u32 = 0x00080000;
const ERROR_PIPE_CONNECTED: u32 = 535;

#[link(name = "kernel32")]
extern "system" {
    fn CreateNamedPipeW(
        lpName: PCWSTR,
        dwOpenMode: u32,
        dwPipeMode: u32,
        nMaxInstances: u32,
        nOutBufferSize: u32,
        nInBufferSize: u32,
        nDefaultTimeOut: u32,
        lpSecurityAttributes: *mut c_void,
    ) -> HANDLE;

    fn ConnectNamedPipe(hNamedPipe: HANDLE, lpOverlapped: *mut c_void) -> i32;
}

fn to_wide(s: &str) -> Vec<u16> {
    OsStr::new(s).encode_wide().chain(Some(0)).collect()
}

fn create_pipe(name: &[u16]) -> Result<HANDLE> {
    unsafe {
        let handle = CreateNamedPipeW(
            PCWSTR(name.as_ptr()),
            PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,
            BUFFER_SIZE,
            BUFFER_SIZE,
            0,
            null_mut(),
        );

        if handle == INVALID_HANDLE_VALUE {
            let error_code = GetLastError().0 as i32;
            Err(windows::core::Error::from(windows::core::HRESULT(error_code)))
        } else {
            Ok(handle)
        }
    }
}

pub fn start_pipe_listener() {
    let pipe_name = to_wide(PIPE_NAME);
    eprintln!("IPC listener thread starting for pipe: {}", PIPE_NAME);
    thread::spawn(move || loop {
        match create_pipe(&pipe_name) {
            Ok(pipe_handle) => {
                eprintln!("IPC created named pipe, waiting for client connection");
                let connected = unsafe { ConnectNamedPipe(pipe_handle, null_mut()) != 0 };
                if !connected {
                    let error = unsafe { GetLastError() };
                    if error.0 != ERROR_PIPE_CONNECTED {
                        eprintln!("IPC connect failed: {}", error.0);
                        continue;
                    }
                }
                eprintln!("IPC client connected");

                let raw_handle = pipe_handle.0 as RawHandle;
                let file = unsafe { File::from_raw_handle(raw_handle) };
                let mut reader = BufReader::new(file.try_clone().unwrap());
                let mut writer = file;
                let mut line = String::new();

                while let Ok(bytes_read) = reader.read_line(&mut line) {
                    if bytes_read == 0 {
                        break;
                    }

                    let trimmed = line.trim_end();
                    if trimmed.is_empty() {
                        line.clear();
                        continue;
                    }

                    eprintln!("IPC raw request: {}", trimmed);
                    if let Err(err) = app::handle_raw_message(trimmed, &mut writer) {
                        eprintln!("Host app command error: {:?}", err);
                        let response = HostResponse {
                            type_: "response".to_string(),
                            request_id: "".to_string(),
                            status: "nack".to_string(),
                            message: Some("Host application error".to_string()),
                        };
                        let _ = write_response(&response, &mut writer);
                    }

                    line.clear();
                }
            }
            Err(err) => {
                eprintln!("IPC failed to create pipe: {:?}", err);
                thread::sleep(Duration::from_secs(1));
            }
        }
    });
}

fn write_response<W: Write>(response: &HostResponse, writer: &mut W) -> std::io::Result<()> {
    let text = serde_json::to_string(response)?;
    eprintln!("IPC write_response: {}", text);
    writer.write_all(text.as_bytes())?;
    writer.write_all(b"\n")?;
    writer.flush()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn writes_valid_json_response() {
        let response = HostResponse {
            type_: "response".to_string(),
            request_id: "test-id".to_string(),
            status: "ack".to_string(),
            message: Some("ok".to_string()),
        };

        let mut buffer = Cursor::new(Vec::new());
        write_response(&response, &mut buffer).expect("write response");
        let output = String::from_utf8(buffer.into_inner()).expect("utf8 response");

        let parsed: HostResponse = serde_json::from_str(output.trim()).expect("parse response json");
        assert_eq!(parsed.request_id, "test-id");
        assert_eq!(parsed.status, "ack");
    }
}
