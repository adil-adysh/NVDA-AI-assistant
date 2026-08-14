use std::ffi::{c_void, OsStr};
use std::fs::File;
use std::io::{self, BufRead, BufReader, Write};
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
use crate::protocol::{self, ProtocolError, ProtocolErrorKind};

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
const EVENT_CHANNEL_CAPACITY: usize = 256;
const MAX_FRAME_BYTES: usize = 4 * 1024 * 1024;

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

				loop {
					let reader_line = match read_frame(&mut reader) {
						Ok(Some(line)) => line,
						Ok(None) => break,
						Err(error) => {
							logger::error(&format!("IPC rejected command frame: {:?}", error));
							break;
						}
					};

					let trimmed = reader_line.trim_end();
					if trimmed.is_empty() {
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
						let fallback = ProtocolError::new(
							ProtocolErrorKind::UiDispatchFailed,
							None,
							"Host application error",
						);
						let _ = write_json_value(&protocol::build_error(None, &fallback), &mut *writer_guard);
					}

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

fn read_frame<R: BufRead>(reader: &mut R) -> io::Result<Option<String>> {
	let mut bytes = Vec::new();
	let bytes_read = reader.read_until(b'\n', &mut bytes)?;
	if bytes_read == 0 {
		return Ok(None);
	}
	if bytes.len() > MAX_FRAME_BYTES {
		return Err(io::Error::new(
			io::ErrorKind::InvalidData,
			format!("IPC frame exceeds {} bytes", MAX_FRAME_BYTES),
		));
	}
	if !bytes.ends_with(b"\n") {
		return Err(io::Error::new(
			io::ErrorKind::UnexpectedEof,
			"IPC frame was not newline terminated",
		));
	}
	String::from_utf8(bytes)
		.map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
	.map(Some)
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
				let (event_tx, event_rx) = mpsc::sync_channel::<String>(EVENT_CHANNEL_CAPACITY);
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

fn write_json_value<W: Write>(value: &serde_json::Value, writer: &mut W) -> std::io::Result<()> {
	let text = serde_json::to_string(value)?;
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

#[cfg(test)]
mod tests {
	use super::*;
	use std::io::Cursor;

	#[test]
	fn read_frame_requires_newline_termination() {
		let mut reader = Cursor::new(b"{}".to_vec());
		let error = read_frame(&mut reader).expect_err("unterminated frame should fail");
		assert_eq!(error.kind(), io::ErrorKind::UnexpectedEof);
	}

	#[test]
	fn read_frame_returns_one_utf8_frame() {
		let mut reader = Cursor::new(b"{\"id\":1}\nnext\n".to_vec());
		assert_eq!(read_frame(&mut reader).unwrap(), Some("{\"id\":1}\n".to_string()));
		assert_eq!(read_frame(&mut reader).unwrap(), Some("next\n".to_string()));
	}
}
