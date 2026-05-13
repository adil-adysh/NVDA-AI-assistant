use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const LEGACY_PROTOCOL_VERSION: u32 = 1;
pub const UI_HOST_SCHEMA: &str = "nvda.ui_host";
pub const UI_HOST_PROTOCOL_VERSION: u32 = 2;

fn default_protocol_version() -> u32 {
	LEGACY_PROTOCOL_VERSION
}

fn default_command_type() -> String {
	"command".to_string()
}

#[derive(Deserialize, Serialize, Debug)]
pub struct HostCommand {
	pub action: String,
	#[serde(default)]
	pub request_id: String,
	#[serde(default = "default_protocol_version")]
	pub protocol_version: u32,
	#[serde(default = "default_command_type")]
	#[serde(rename = "type")]
	pub type_: String,
	#[serde(default)]
	pub use_case_id: Option<String>,
	#[serde(default)]
	pub payload: Value,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProtocolErrorKind {
	InvalidJson,
	InvalidSchema,
	UnsupportedVersion,
	UnexpectedMessageType,
	UnsupportedCommand,
	QueueFull,
	UiDispatchFailed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProtocolError {
	pub kind: ProtocolErrorKind,
	pub request_id: Option<String>,
	pub message: String,
}

impl ProtocolError {
	pub fn new(kind: ProtocolErrorKind, request_id: Option<String>, message: impl Into<String>) -> Self {
		Self {
			kind,
			request_id,
			message: message.into(),
		}
	}
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MessageSource {
	NvdaAddon,
	UiHost,
	WebUi,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AckStage {
	Accepted,
	Enqueued,
	DispatchedToUi,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
	InvalidJson,
	InvalidSchema,
	UnsupportedVersion,
	UnexpectedMessageType,
	UnsupportedCommand,
	QueueFull,
	UiNotReady,
	UiDispatchFailed,
	InternalError,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProtocolEnvelope {
	pub schema: String,
	pub version: u32,
	pub id: String,
	#[serde(default, skip_serializing_if = "Option::is_none")]
	pub correlation_id: Option<String>,
	pub source: MessageSource,
	#[serde(flatten)]
	pub body: ProtocolBody,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ProtocolBody {
	Command { command: CommandEnvelope },
	Event { event: EventEnvelope },
	Ack {
		acked_id: String,
		stage: AckStage,
		#[serde(default, skip_serializing_if = "Option::is_none")]
		detail: Option<String>,
	},
	Error {
		#[serde(default, skip_serializing_if = "Option::is_none")]
		failed_id: Option<String>,
		code: ErrorCode,
		detail: String,
		retriable: bool,
	},
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CommandEnvelope {
	pub name: CommandName,
	pub payload: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EventEnvelope {
	pub name: EventName,
	pub payload: Value,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ParsedCommand {
	pub message_id: String,
	pub correlation_id: Option<String>,
	pub response_mode: ResponseMode,
	pub payload: UiCommand,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResponseMode {
	Legacy,
	V2,
}

// ── Generated enums + UiCommand impl ────────────────────────────────
// See scripts/protocol.yaml for the canonical definition.
include!("protocol_commands.rs");
// ────────────────────────────────────────────────────────────────────

pub fn parse_inbound_command(raw: &str) -> Result<ParsedCommand, ProtocolError> {
	match serde_json::from_str::<ProtocolEnvelope>(raw) {
		Ok(envelope) => parse_v2_envelope(envelope),
		Err(v2_error) => match serde_json::from_str::<HostCommand>(raw) {
			Ok(command) => parse_legacy_command(command),
			Err(_) => Err(ProtocolError::new(
				ProtocolErrorKind::InvalidJson,
				None,
				format!("Unable to parse protocol message: {v2_error}"),
			)),
		},
	}
}

fn parse_v2_envelope(envelope: ProtocolEnvelope) -> Result<ParsedCommand, ProtocolError> {
	if envelope.schema != UI_HOST_SCHEMA {
		return Err(ProtocolError::new(
			ProtocolErrorKind::InvalidSchema,
			Some(envelope.id),
			format!("Unsupported schema: {}", envelope.schema),
		));
	}
	if envelope.version != UI_HOST_PROTOCOL_VERSION {
		return Err(ProtocolError::new(
			ProtocolErrorKind::UnsupportedVersion,
			Some(envelope.id),
			format!("Unsupported protocol version: {}", envelope.version),
		));
	}

	match envelope.body {
		ProtocolBody::Command { command } => Ok(ParsedCommand {
			message_id: envelope.id,
			correlation_id: envelope.correlation_id,
			response_mode: ResponseMode::V2,
			payload: UiCommand::from_command_name(command.name, command.payload),
		}),
		_ => Err(ProtocolError::new(
			ProtocolErrorKind::UnexpectedMessageType,
			Some(envelope.id),
			"Inbound envelope must be a command",
		)),
	}
}

fn parse_legacy_command(command: HostCommand) -> Result<ParsedCommand, ProtocolError> {
	if command.protocol_version != LEGACY_PROTOCOL_VERSION {
		return Err(ProtocolError::new(
			ProtocolErrorKind::UnsupportedVersion,
			Some(command.request_id),
			format!("Unsupported protocol version: {}", command.protocol_version),
		));
	}
	let request_id = command.request_id;
	let payload = UiCommand::from_legacy_action(&command.action, command.payload).map_err(|error| {
		ProtocolError::new(error.kind, Some(request_id.clone()), error.message)
	})?;
	Ok(ParsedCommand {
		message_id: request_id,
		correlation_id: None,
		response_mode: ResponseMode::Legacy,
		payload,
	})
}

pub fn to_webview_envelope(command: &ParsedCommand) -> ProtocolEnvelope {
	ProtocolEnvelope {
		schema: UI_HOST_SCHEMA.to_string(),
		version: UI_HOST_PROTOCOL_VERSION,
		id: next_message_id("ui"),
		correlation_id: Some(command.message_id.clone()),
		source: MessageSource::UiHost,
		body: ProtocolBody::Command {
			command: CommandEnvelope {
				name: command.payload.command_name(),
				payload: command.payload.payload(),
			},
		},
	}
}

pub fn build_ack(command: &ParsedCommand, stage: AckStage, detail: Option<String>) -> Value {
	match command.response_mode {
		ResponseMode::Legacy => serde_json::to_value(HostResponse {
			type_: "response".to_string(),
			request_id: command.message_id.clone(),
			status: "ack".to_string(),
			message: detail,
		})
		.expect("serialize legacy ack"),
		ResponseMode::V2 => serde_json::to_value(ProtocolEnvelope {
			schema: UI_HOST_SCHEMA.to_string(),
			version: UI_HOST_PROTOCOL_VERSION,
			id: next_message_id("ack"),
			correlation_id: Some(command.message_id.clone()),
			source: MessageSource::UiHost,
			body: ProtocolBody::Ack {
				acked_id: command.message_id.clone(),
				stage,
				detail,
			},
		})
		.expect("serialize v2 ack"),
	}
}

pub fn build_error(response_mode: ResponseMode, request_id: Option<String>, error: &ProtocolError) -> Value {
	match response_mode {
		ResponseMode::Legacy => serde_json::to_value(HostResponse {
			type_: "response".to_string(),
			request_id: request_id.unwrap_or_default(),
			status: "nack".to_string(),
			message: Some(error.message.clone()),
		})
		.expect("serialize legacy error"),
		ResponseMode::V2 => serde_json::to_value(ProtocolEnvelope {
			schema: UI_HOST_SCHEMA.to_string(),
			version: UI_HOST_PROTOCOL_VERSION,
			id: next_message_id("err"),
			correlation_id: request_id.clone(),
			source: MessageSource::UiHost,
			body: ProtocolBody::Error {
				failed_id: request_id,
				code: protocol_error_code(&error.kind),
				detail: error.message.clone(),
				retriable: matches!(error.kind, ProtocolErrorKind::UnexpectedMessageType),
			},
		})
		.expect("serialize v2 error"),
	}
}

fn protocol_error_code(kind: &ProtocolErrorKind) -> ErrorCode {
	match kind {
		ProtocolErrorKind::InvalidJson => ErrorCode::InvalidJson,
		ProtocolErrorKind::InvalidSchema => ErrorCode::InvalidSchema,
		ProtocolErrorKind::UnsupportedVersion => ErrorCode::UnsupportedVersion,
		ProtocolErrorKind::UnexpectedMessageType => ErrorCode::UnexpectedMessageType,
		ProtocolErrorKind::UnsupportedCommand => ErrorCode::UnsupportedCommand,
		ProtocolErrorKind::QueueFull => ErrorCode::QueueFull,
		ProtocolErrorKind::UiDispatchFailed => ErrorCode::UiDispatchFailed,
	}
}

fn next_message_id(prefix: &str) -> String {
	use std::sync::atomic::{AtomicU64, Ordering};
	use std::time::{SystemTime, UNIX_EPOCH};

	static COUNTER: AtomicU64 = AtomicU64::new(1);
	let ts = SystemTime::now()
		.duration_since(UNIX_EPOCH)
		.map(|duration| duration.as_millis())
		.unwrap_or_default();
	let seq = COUNTER.fetch_add(1, Ordering::Relaxed);
	format!("{prefix}-{ts}-{seq}")
}

#[derive(Deserialize, Serialize, Debug)]
pub struct HostResponse {
	#[serde(rename = "type")]
	pub type_: String,
	pub request_id: String,
	pub status: String,
	#[serde(skip_serializing_if = "Option::is_none")]
	pub message: Option<String>,
}

#[derive(Serialize, Debug)]
#[allow(dead_code)]
pub struct HostEvent {
	#[serde(rename = "type")]
	pub type_: String,
	pub event: String,
	pub payload: Value,
	#[serde(skip_serializing_if = "Option::is_none")]
	pub request_id: Option<String>,
}

#[cfg(test)]
mod tests {
	use super::*;
	use serde_json::json;

	#[test]
	fn host_command_serializes_and_deserializes() {
		let command = HostCommand {
			action: "display_result".to_string(),
			request_id: "test-id".to_string(),
			protocol_version: 1,
			type_: "command".to_string(),
			use_case_id: Some("use-case-1".to_string()),
			payload: json!({ "output_text": "Hello" }),
		};

		let json_text = serde_json::to_string(&command).expect("serialize HostCommand");
		let parsed: HostCommand = serde_json::from_str(&json_text).expect("deserialize HostCommand");

		assert_eq!(parsed.action, "display_result");
		assert_eq!(parsed.request_id, "test-id");
		assert_eq!(parsed.protocol_version, 1);
		assert_eq!(parsed.type_, "command");
		assert_eq!(parsed.use_case_id.as_deref(), Some("use-case-1"));
		assert_eq!(parsed.payload["output_text"], "Hello");
	}

	#[test]
	fn host_response_serializes_and_deserializes() {
		let response = HostResponse {
			type_: "response".to_string(),
			request_id: "test-id".to_string(),
			status: "ack".to_string(),
			message: Some("ok".to_string()),
		};

		let json_text = serde_json::to_string(&response).expect("serialize HostResponse");
		let parsed: HostResponse = serde_json::from_str(&json_text).expect("deserialize HostResponse");

		assert_eq!(parsed.type_, "response");
		assert_eq!(parsed.status, "ack");
		assert_eq!(parsed.message.as_deref(), Some("ok"));
	}

	#[test]
	fn parses_legacy_command_into_typed_model() {
		let parsed = parse_inbound_command(r#"{"type":"command","action":"display_result","request_id":"legacy-1","protocol_version":1,"payload":{"output_text":"Hello"}}"#)
			.expect("parse legacy command");

		assert_eq!(parsed.message_id, "legacy-1");
		assert_eq!(parsed.response_mode, ResponseMode::Legacy);
		assert_eq!(parsed.payload.command_name(), CommandName::RenderDisplay);
	}

	#[test]
	fn parses_v2_command_into_typed_model() {
		let parsed = parse_inbound_command(r#"{"schema":"nvda.ui_host","version":2,"id":"msg-1","correlation_id":null,"source":"nvda_addon","type":"command","command":{"name":"open_chat","payload":{"title":"Chat"}}}"#)
			.expect("parse v2 command");

		assert_eq!(parsed.message_id, "msg-1");
		assert_eq!(parsed.response_mode, ResponseMode::V2);
		assert_eq!(parsed.payload.command_name(), CommandName::OpenChat);
	}

	#[test]
	fn parses_sync_session_v2_command() {
		let parsed = parse_inbound_command(r#"{"schema":"nvda.ui_host","version":2,"id":"msg-sync","correlation_id":"conv-1","source":"nvda_addon","type":"command","command":{"name":"sync_session","payload":{"conversation_id":"conv-1","metadata":{"think_enabled":true}}}}"#)
			.expect("parse sync_session command");

		assert_eq!(parsed.message_id, "msg-sync");
		assert_eq!(parsed.correlation_id.as_deref(), Some("conv-1"));
		assert_eq!(parsed.response_mode, ResponseMode::V2);
		assert_eq!(parsed.payload.command_name(), CommandName::SyncSession);
		assert_eq!(parsed.payload.payload()["conversation_id"], "conv-1");
	}

	#[test]
	fn parses_chat_stream_delta_v2_command() {
		let parsed = parse_inbound_command(r#"{"schema":"nvda.ui_host","version":2,"id":"msg-stream","correlation_id":"conv-1","source":"nvda_addon","type":"command","command":{"name":"chat_stream_delta","payload":{"conversation_id":"conv-1","message_id":"assistant-1","delta":"Hello","sequence":2}}}"#)
			.expect("parse chat_stream_delta command");

		assert_eq!(parsed.message_id, "msg-stream");
		assert_eq!(parsed.payload.command_name(), CommandName::ChatStreamDelta);
		assert_eq!(parsed.payload.payload()["delta"], "Hello");
		assert_eq!(parsed.payload.payload()["sequence"], 2);
	}
}
