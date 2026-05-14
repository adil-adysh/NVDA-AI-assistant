use std::ffi::{c_void, OsStr};
use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::{FromRawHandle, RawHandle};
use std::ptr::null_mut;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;

use windows::core::{PCWSTR, Result};
use windows::Win32::Foundation::{GetLastError, HANDLE, INVALID_HANDLE_VALUE};

use crate::app;
use crate::logger;
use crate::protocol::HostResponse;

use super::state::{clear_ui_event_sender, install_ui_event_sender, requeue_ui_events_after_disconnect};
use super::watchdog;

const COMMAND_PIPE_NAME: &str = r"\\.\pipe\nvda_ai_assistant_ui_cmd";
const EVENT_PIPE_NAME: &str = r"\\.\pipe\nvda_ai_assistant_ui_evt";
const BUFFER_SIZE: u32 = 65536;
const PIPE_ACCESS_DUPLEX: u32 = 0x00000003;
const PIPE_TYPE_BYTE: u32 = 0x00000000;
const PIPE_READMODE_BYTE: u32 = 0x00000000;
const PIPE_WAIT: u32 = 0x00000000;
const PIPE_UNLIMITED_INSTANCES: u32 = 255;
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
			PIPE_ACCESS_DUPLEX,
			PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
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

pub(crate) fn start_pipe_listener() {
	start_command_pipe_listener();
	start_event_pipe_listener();
}

fn start_command_pipe_listener() {
	let pipe_name = to_wide(COMMAND_PIPE_NAME);
	logger::info(&format!("IPC command listener thread starting for pipe: {}", COMMAND_PIPE_NAME));
	thread::spawn(move || loop {
		match create_pipe(&pipe_name) {
			Ok(pipe_handle) => {
				if !connect_pipe(pipe_handle) {
					continue;
				}
				logger::info("IPC command client connected");
				watchdog::touch();

				let raw_handle = pipe_handle.0 as RawHandle;
				let file = unsafe { File::from_raw_handle(raw_handle) };
				let reader_file = match file.try_clone() {
					Ok(clone) => clone,
					Err(error) => {
						logger::error(&format!("IPC failed to clone command pipe handle: {:?}", error));
						continue;
					}
				};
				let mut reader = BufReader::new(reader_file);
				let writer = Arc::new(Mutex::new(file));

				let mut reader_line = String::new();
				while let Ok(bytes_read) = reader.read_line(&mut reader_line) {
					if bytes_read == 0 {
						break;
					}

					let trimmed = reader_line.trim_end();
					if trimmed.is_empty() {
						reader_line.clear();
						continue;
					}

					logger::debug(&format!(
						"IPC raw request len={} preview={}",
						trimmed.len(),
						logger::preview(trimmed, 160)
					));
					let mut writer_guard = writer.lock().unwrap();
					if let Err(err) = app::handle_raw_message(trimmed, &mut *writer_guard) {
						logger::error(&format!("Host app command error: {:?}", err));
						let response = HostResponse {
							type_: "response".to_string(),
							request_id: "".to_string(),
							status: "nack".to_string(),
							message: Some("Host application error".to_string()),
						};
						let _ = write_response(&response, &mut *writer_guard);
					}

					reader_line.clear();
				}
				watchdog::touch(); // client disconnected — reset idle timer
			}
			Err(err) => {
				logger::error(&format!("IPC failed to create command pipe: {:?}", err));
				thread::sleep(Duration::from_secs(1));
			}
		}
	});
}

fn start_event_pipe_listener() {
	let pipe_name = to_wide(EVENT_PIPE_NAME);
	logger::info(&format!("IPC event listener thread starting for pipe: {}", EVENT_PIPE_NAME));
	thread::spawn(move || loop {
		match create_pipe(&pipe_name) {
			Ok(pipe_handle) => {
				if !connect_pipe(pipe_handle) {
					continue;
				}
				logger::info("IPC event client connected");

				let raw_handle = pipe_handle.0 as RawHandle;
				let mut file = unsafe { File::from_raw_handle(raw_handle) };
				let (event_tx, event_rx) = mpsc::channel::<String>();
				let mut pending_messages = install_ui_event_sender(event_tx.clone());
				while let Some(message) = pending_messages.pop_front() {
					if let Err(error) = event_tx.send(message) {
						logger::warn(&format!("IPC failed to flush queued UI event: {:?}", error));
						requeue_ui_events_after_disconnect(Some(error.0), pending_messages);
						break;
					}
				}

				for message in event_rx {
					if let Err(err) = write_text(&message, &mut file) {
						logger::warn(&format!("IPC failed to write UI event: {:?}", err));
						requeue_ui_events_after_disconnect(Some(message), Default::default());
						break;
					}
				}

				clear_ui_event_sender();
			}
			Err(err) => {
				logger::error(&format!("IPC failed to create event pipe: {:?}", err));
				thread::sleep(Duration::from_secs(1));
			}
		}
	});
}

fn connect_pipe(pipe_handle: HANDLE) -> bool {
	logger::info("IPC created named pipe, waiting for client connection");
	let connected = unsafe { ConnectNamedPipe(pipe_handle, null_mut()) != 0 };
	if !connected {
		let error = unsafe { GetLastError() };
		if error.0 != ERROR_PIPE_CONNECTED {
			logger::warn(&format!("IPC connect failed: {}", error.0));
			return false;
		}
	}
	true
}

fn write_response<W: Write>(response: &HostResponse, writer: &mut W) -> std::io::Result<()> {
	let text = serde_json::to_string(response)?;
	logger::debug(&format!(
		"IPC write_response len={} preview={}",
		text.len(),
		logger::preview(&text, 160)
	));
	write_text(&text, writer)
}

fn write_text<W: Write>(text: &str, writer: &mut W) -> std::io::Result<()> {
	writer.write_all(text.as_bytes())?;
	writer.write_all(b"\n")?;
	writer.flush()
}
