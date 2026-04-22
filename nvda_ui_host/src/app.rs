use std::io::Write;

use windows::core::Result;

use crate::protocol::{self, AckStage, ParsedCommand, ProtocolError, ResponseMode};
use crate::window;

pub fn handle_raw_message(raw: &str, writer: &mut impl Write) -> Result<()> {
    match protocol::parse_inbound_command(raw) {
        Ok(command) => handle_command(command, writer),
        Err(error) => {
            let response_mode = infer_response_mode(raw);
            write_json_value(&protocol::build_error(response_mode, error.request_id.clone(), &error), writer)
        }
    }
}

pub fn handle_command(command: ParsedCommand, writer: &mut impl Write) -> Result<()> {
    eprintln!("Host app handling message_id={} command={}", command.message_id, command.payload.as_legacy_action());
    if matches!(command.payload, protocol::UiCommand::HealthCheck) {
        return write_json_value(&protocol::build_ack(&command, AckStage::Accepted, None), writer);
    }

    let webview_message = serde_json::to_string(&protocol::to_webview_envelope(&command))
        .map_err(|error| windows::core::Error::new(windows::core::HRESULT(0), error.to_string()))?;
    eprintln!("Host app forwarding normalized command to UI thread: {}", webview_message);
    if let Err(dispatch_error) = window::post_host_command(webview_message) {
        let (kind, message) = match dispatch_error {
            window::DispatchError::QueueFull => (protocol::ProtocolErrorKind::QueueFull, "Host dispatch queue is full"),
            window::DispatchError::QueueDisconnected => (protocol::ProtocolErrorKind::UiDispatchFailed, "Host dispatch queue is disconnected"),
            window::DispatchError::NotInitialized => (protocol::ProtocolErrorKind::UiDispatchFailed, "Host window dispatch is not initialized"),
        };
        let error = ProtocolError::new(kind, Some(command.message_id.clone()), message);
        return write_json_value(&protocol::build_error(command.response_mode, Some(command.message_id.clone()), &error), writer);
    }
    write_json_value(&protocol::build_ack(&command, AckStage::Enqueued, None), writer)
}

fn write_json_value(value: &serde_json::Value, writer: &mut impl Write) -> Result<()> {
    eprintln!("Host app sending response: {}", value);
    serde_json::to_writer(&mut *writer, value)
        .map_err(|error| windows::core::Error::new(windows::core::HRESULT(0), error.to_string()))?;
    writer
        .write_all(b"\n")
        .map_err(|error| windows::core::Error::new(windows::core::HRESULT(0), error.to_string()))
}

fn infer_response_mode(raw: &str) -> ResponseMode {
    match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(serde_json::Value::Object(map)) if map.get("schema").is_some() => ResponseMode::V2,
        _ => ResponseMode::Legacy,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{from_str, Value};
    use std::io::Cursor;

    #[test]
    fn handle_health_check_returns_ack() {
        let mut buffer = Cursor::new(Vec::new());
        handle_raw_message(
            r#"{"type":"command","action":"health_check","request_id":"test-health","protocol_version":1,"payload":{}}"#,
            &mut buffer,
        )
        .expect("health_check should succeed");

        let output = String::from_utf8(buffer.into_inner()).expect("utf8 response");
        let response: protocol::HostResponse = from_str(output.trim()).expect("parse response");
        assert_eq!(response.status, "ack");
        assert_eq!(response.request_id, "test-health");
        assert_eq!(response.message, None);
    }

    #[test]
    fn handle_unknown_action_returns_nack() {
        let mut buffer = Cursor::new(Vec::new());
        handle_raw_message(
            r#"{"type":"command","action":"bogus_action","request_id":"test-bogus","protocol_version":1,"payload":{}}"#,
            &mut buffer,
        )
        .expect("unknown action should still return a response");

        let output = String::from_utf8(buffer.into_inner()).expect("utf8 response");
        let response: protocol::HostResponse = from_str(output.trim()).expect("parse response");
        assert_eq!(response.status, "nack");
        assert_eq!(response.request_id, "test-bogus");
        assert_eq!(response.message.as_deref(), Some("Unsupported action: bogus_action"));
    }

    #[test]
    fn handle_unsupported_protocol_version_returns_nack() {
        let mut buffer = Cursor::new(Vec::new());
        handle_raw_message(
            r#"{"type":"command","action":"health_check","request_id":"test-version","protocol_version":999,"payload":{}}"#,
            &mut buffer,
        )
        .expect("unsupported version should still return a response");

        let output = String::from_utf8(buffer.into_inner()).expect("utf8 response");
        let response: protocol::HostResponse = from_str(output.trim()).expect("parse response");
        assert_eq!(response.status, "nack");
        assert_eq!(response.request_id, "test-version");
        assert_eq!(response.message.as_deref(), Some("Unsupported protocol version: 999"));
    }

    #[test]
    fn handle_v2_health_check_returns_v2_ack() {
        let mut buffer = Cursor::new(Vec::new());
        handle_raw_message(
            r#"{"schema":"nvda.ui_host","version":2,"id":"msg-1","correlation_id":null,"source":"nvda_addon","type":"command","command":{"name":"health_check","payload":{}}}"#,
            &mut buffer,
        )
        .expect("v2 health check should succeed");

        let output = String::from_utf8(buffer.into_inner()).expect("utf8 response");
        let response: Value = from_str(output.trim()).expect("parse response");
        assert_eq!(response["type"], "ack");
        assert_eq!(response["acked_id"], "msg-1");
        assert_eq!(response["stage"], "accepted");
    }
}
