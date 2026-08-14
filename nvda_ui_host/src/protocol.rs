use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const UI_HOST_SCHEMA: &str = "nvda.ui_host";
pub const UI_HOST_PROTOCOL_VERSION: u32 = 2;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProtocolErrorKind {
	InvalidJson,
	InvalidPayload,
	InvalidSchema,
	UnsupportedVersion,
	UnexpectedMessageType,
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
	InvalidPayload,
	InvalidSchema,
	UnsupportedVersion,
	UnexpectedMessageType,
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
	pub payload: UiCommand,
}

// ── Generated enums + UiCommand impl ────────────────────────────────
// See scripts/protocol.yaml for the canonical definition.
include!("protocol_commands.rs");
// ────────────────────────────────────────────────────────────────────

pub fn parse_inbound_command(raw: &str) -> Result<ParsedCommand, ProtocolError> {
	let envelope = serde_json::from_str::<ProtocolEnvelope>(raw).map_err(|error| {
		ProtocolError::new(ProtocolErrorKind::InvalidJson, None, format!("Unable to parse protocol message: {error}"))
	})?;
	parse_v2_envelope(envelope)
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
		ProtocolBody::Command { command } => {
			validate_payload(&command.name, &command.payload, Some(envelope.id.clone()))?;
			Ok(ParsedCommand {
				message_id: envelope.id,
				correlation_id: envelope.correlation_id,
				payload: UiCommand::from_command_name(command.name, command.payload),
			})
		}
		_ => Err(ProtocolError::new(
			ProtocolErrorKind::UnexpectedMessageType,
			Some(envelope.id),
			"Inbound envelope must be a command",
		)),
	}
}

fn validate_payload(
	command: &CommandName,
	payload: &Value,
	request_id: Option<String>,
) -> Result<(), ProtocolError> {
	let Some(payload_object) = payload.as_object() else {
		return Err(ProtocolError::new(
			ProtocolErrorKind::InvalidPayload,
			request_id,
			format!("Payload for {command:?} must be a JSON object"),
		));
	};
	let missing: Vec<&str> = required_payload_fields(command)
		.iter()
		.copied()
		.filter(|field| !payload_object.contains_key(*field))
		.collect();
	if !missing.is_empty() {
		return Err(ProtocolError::new(
			ProtocolErrorKind::InvalidPayload,
			request_id,
			format!("Payload for {command:?} is missing required fields: {}", missing.join(", ")),
		));
	}
	for (field, expected_type) in required_payload_types(command) {
		let value = payload_object.get(*field).expect("required field checked above");
		let valid = match *expected_type {
			"string" => value.is_string(),
			"integer" => value.as_i64().is_some() || value.as_u64().is_some(),
			"boolean" => value.is_boolean(),
			"array" => value.is_array(),
			"object" => value.is_object(),
			"json" => true,
			_ => false,
		};
		if !valid {
			return Err(ProtocolError::new(
				ProtocolErrorKind::InvalidPayload,
				request_id,
				format!("Payload for {command:?} field '{field}' must be {expected_type}"),
			));
		}
	}
	Ok(())
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
	serde_json::to_value(ProtocolEnvelope {
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
	.expect("serialize v2 ack")
}

pub fn build_error(request_id: Option<String>, error: &ProtocolError) -> Value {
	serde_json::to_value(ProtocolEnvelope {
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
	.expect("serialize v2 error")
}

fn protocol_error_code(kind: &ProtocolErrorKind) -> ErrorCode {
	match kind {
		ProtocolErrorKind::InvalidJson => ErrorCode::InvalidJson,
		ProtocolErrorKind::InvalidPayload => ErrorCode::InvalidPayload,
		ProtocolErrorKind::InvalidSchema => ErrorCode::InvalidSchema,
		ProtocolErrorKind::UnsupportedVersion => ErrorCode::UnsupportedVersion,
		ProtocolErrorKind::UnexpectedMessageType => ErrorCode::UnexpectedMessageType,
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

	#[test]
	fn parses_v2_command_into_typed_model() {
		let parsed = parse_inbound_command(r#"{"schema":"nvda.ui_host","version":2,"id":"msg-1","correlation_id":null,"source":"nvda_addon","type":"command","command":{"name":"open_chat","payload":{"title":"Chat"}}}"#)
			.expect("parse v2 command");

		assert_eq!(parsed.message_id, "msg-1");
		assert_eq!(parsed.payload.command_name(), CommandName::OpenChat);
	}

	#[test]
	fn parses_sync_session_v2_command() {
		let parsed = parse_inbound_command(r#"{"schema":"nvda.ui_host","version":2,"id":"msg-sync","correlation_id":"conv-1","source":"nvda_addon","type":"command","command":{"name":"sync_session","payload":{"conversation_id":"conv-1","metadata":{"think_enabled":true}}}}"#)
			.expect("parse sync_session command");

		assert_eq!(parsed.message_id, "msg-sync");
		assert_eq!(parsed.correlation_id.as_deref(), Some("conv-1"));
		assert_eq!(parsed.payload.command_name(), CommandName::SyncSession);
		assert_eq!(parsed.payload.payload()["conversation_id"], "conv-1");
	}

	#[test]
	fn parses_chat_stream_delta_v2_command() {
		let parsed = parse_inbound_command(r#"{"schema":"nvda.ui_host","version":2,"id":"msg-stream","correlation_id":"conv-1","source":"nvda_addon","type":"command","command":{"name":"chat_stream_delta","payload":{"conversation_id":"conv-1","message_id":"assistant-1","stream_id":"stream-1","delta":"Hello","sequence":2}}}"#)
			.expect("parse chat_stream_delta command");

		assert_eq!(parsed.message_id, "msg-stream");
		assert_eq!(parsed.payload.command_name(), CommandName::ChatStreamDelta);
		assert_eq!(parsed.payload.payload()["delta"], "Hello");
		assert_eq!(parsed.payload.payload()["sequence"], 2);
	}

	#[test]
	fn rejects_v2_command_with_missing_required_payload_field() {
		let error = parse_inbound_command(
			r#"{"schema":"nvda.ui_host","version":2,"id":"msg-stream","correlation_id":null,"source":"nvda_addon","type":"command","command":{"name":"chat_stream_delta","payload":{"message_id":"assistant-1","delta":"Hello","sequence":2}}}"#,
		)
		.expect_err("missing stream_id should be rejected");

		assert_eq!(error.kind, ProtocolErrorKind::InvalidPayload);
		assert!(error.message.contains("stream_id"));
	}

	#[test]
	fn rejects_v2_command_with_invalid_required_payload_type() {
		let error = parse_inbound_command(
			r#"{"schema":"nvda.ui_host","version":2,"id":"msg-stream","correlation_id":null,"source":"nvda_addon","type":"command","command":{"name":"chat_stream_delta","payload":{"message_id":"assistant-1","stream_id":"stream-1","delta":"Hello","sequence":"2"}}}"#,
		)
		.expect_err("string sequence should be rejected");

		assert_eq!(error.kind, ProtocolErrorKind::InvalidPayload);
		assert!(error.message.contains("sequence"));
	}

	#[test]
	fn parses_shared_v2_fixture() {
		let fixture = include_str!("../../protocol_fixtures/chat_stream_delta_v2.json");
		let parsed = parse_inbound_command(fixture).expect("shared fixture should parse");

		assert_eq!(parsed.payload.command_name(), CommandName::ChatStreamDelta);
		assert_eq!(parsed.payload.payload()["stream_id"], "stream-1");
	}
}
