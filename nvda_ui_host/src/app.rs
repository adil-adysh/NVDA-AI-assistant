use std::io::Write;

use windows::core::Result;

use crate::logger;
use crate::protocol::{self, AckStage, ParsedCommand, ProtocolError, ResponseMode};
use crate::window;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ActivationPolicy {
    NoActivate,
    ActivateIfBackground,
    ActivateAndFocus,
}

fn activation_policy(command: &ParsedCommand) -> ActivationPolicy {
    let payload = command.payload.payload();
    let policy = payload
        .get("attention_policy")
        .and_then(|value| value.as_str())
        .or_else(|| {
            payload
                .get("metadata")
                .and_then(|value| value.as_object())
                .and_then(|metadata| metadata.get("attention_policy"))
                .and_then(|value| value.as_str())
        });

    match policy {
        Some("none") => ActivationPolicy::NoActivate,
        Some("foreground_if_background") => ActivationPolicy::ActivateIfBackground,
        Some("activate_and_focus") => ActivationPolicy::ActivateAndFocus,
        _ => match command.payload {
            protocol::UiCommand::OpenChat(_) => ActivationPolicy::ActivateAndFocus,
            protocol::UiCommand::RenderDisplay(_) | protocol::UiCommand::ShowError(_) => {
                ActivationPolicy::ActivateIfBackground
            }
            protocol::UiCommand::ChatAppend(_)
            | protocol::UiCommand::ChatStreamEnd(_) => ActivationPolicy::ActivateIfBackground,
            protocol::UiCommand::HealthCheck
            | protocol::UiCommand::SyncSession(_)
            | protocol::UiCommand::ChatSetHistory(_)
            | protocol::UiCommand::ChatUpdate(_)
            | protocol::UiCommand::ChatStreamBegin(_)
            | protocol::UiCommand::ChatStreamDelta(_)
            | protocol::UiCommand::ChatStreamAbort(_)
            | protocol::UiCommand::UpdateProgress(_)
            | protocol::UiCommand::CloseWindow(_) => ActivationPolicy::NoActivate,
        },
    }
}

fn requests_webview_focus(command: &ParsedCommand) -> bool {
    let payload = command.payload.payload();
    let focus_target = payload
        .get("focus_target")
        .and_then(|value| value.as_str())
        .or_else(|| {
            payload
                .get("display_presentation")
                .and_then(|value| value.as_object())
                .and_then(|presentation| presentation.get("initial_focus"))
                .and_then(|value| value.as_str())
        })
        .or_else(|| {
            payload
                .get("metadata")
                .and_then(|value| value.as_object())
                .and_then(|metadata| metadata.get("focus_target"))
                .and_then(|value| value.as_str())
        })
        .or_else(|| {
            payload
                .get("metadata")
                .and_then(|value| value.as_object())
                .and_then(|metadata| metadata.get("display_presentation"))
                .and_then(|value| value.as_object())
                .and_then(|presentation| presentation.get("initial_focus"))
                .and_then(|value| value.as_str())
        });

    matches!(focus_target, Some(value) if !value.trim().is_empty())
}

#[cfg(test)]
fn test_command(payload: protocol::UiCommand) -> ParsedCommand {
    ParsedCommand {
        message_id: "test-message".to_string(),
        correlation_id: None,
        response_mode: ResponseMode::V2,
        payload,
    }
}

pub fn handle_raw_message(raw: &str, writer: &mut impl Write) -> Result<()> {
    logger::debug(&format!(
        "Host app received raw message len={} preview={}",
        raw.len(),
        logger::preview(raw, 160)
    ));
    match protocol::parse_inbound_command(raw) {
        Ok(command) => handle_command(command, writer),
        Err(error) => {
            logger::warn(&format!("Host app failed to parse inbound message: {:?}", error));
            let response_mode = infer_response_mode(raw);
            write_json_value(&protocol::build_error(response_mode, error.request_id.clone(), &error), writer)
        }
    }
}

pub fn handle_command(command: ParsedCommand, writer: &mut impl Write) -> Result<()> {
    logger::debug(&format!("Host app handling message_id={} command={}", command.message_id, command.payload.as_legacy_action()));
    if matches!(command.payload, protocol::UiCommand::HealthCheck) {
        logger::debug(&format!("Host app responding to health_check for message_id={}", command.message_id));
        return write_json_value(&protocol::build_ack(&command, AckStage::Accepted, None), writer);
    }

    if let Some(title) = command.payload.payload().get("title").and_then(|value| value.as_str()) {
        if !title.is_empty() {
            window::set_window_title(title);
        }
    }

    if matches!(command.payload, protocol::UiCommand::CloseWindow(_)) {
        if let Err(dispatch_error) = window::request_close_window() {
            let (kind, message) = match dispatch_error {
                window::DispatchError::QueueFull => (protocol::ProtocolErrorKind::QueueFull, "Host dispatch queue is full"),
                window::DispatchError::QueueDisconnected => (protocol::ProtocolErrorKind::UiDispatchFailed, "Host dispatch queue is disconnected"),
                window::DispatchError::NotInitialized => (protocol::ProtocolErrorKind::UiDispatchFailed, "Host window dispatch is not initialized"),
            };
            let error = ProtocolError::new(kind, Some(command.message_id.clone()), message);
            return write_json_value(&protocol::build_error(command.response_mode, Some(command.message_id.clone()), &error), writer);
        }
        return write_json_value(&protocol::build_ack(&command, AckStage::Enqueued, None), writer);
    }

    let webview_message = serde_json::to_string(&protocol::to_webview_envelope(&command))
        .map_err(|error| windows::core::Error::new(windows::core::HRESULT(0), error.to_string()))?;
    logger::info(&format!("Host app forwarding normalized command to UI thread: message_id={} payload={}", command.message_id, command.payload.as_legacy_action()));
    logger::debug(&format!(
        "Host app normalized UI thread command len={} preview={}",
        webview_message.len(),
        logger::preview(&webview_message, 160)
    ));
    if let Err(dispatch_error) = window::post_host_command(
        webview_message,
        activation_policy(&command),
        requests_webview_focus(&command),
    ) {
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
    let serialized = serde_json::to_string(value)
        .map_err(|error| windows::core::Error::new(windows::core::HRESULT(0), error.to_string()))?;
    logger::debug(&format!(
        "Host app sending response len={} preview={}",
        serialized.len(),
        logger::preview(&serialized, 160)
    ));
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
    use serde_json::json;
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

    #[test]
    fn update_progress_does_not_activate_window() {
        let command = test_command(protocol::UiCommand::UpdateProgress(json!({ "message": "Working..." })));
        assert_eq!(activation_policy(&command), ActivationPolicy::NoActivate);
    }

    #[test]
    fn final_render_display_foregrounds_if_backgrounded() {
        let command = test_command(protocol::UiCommand::RenderDisplay(json!({ "output_text": "Done" })));
        assert_eq!(activation_policy(&command), ActivationPolicy::ActivateIfBackground);
    }

    #[test]
    fn open_chat_activates_and_focuses() {
        let command = test_command(protocol::UiCommand::OpenChat(json!({ "title": "Chat" })));
        assert_eq!(activation_policy(&command), ActivationPolicy::ActivateAndFocus);
    }

    #[test]
    fn explicit_attention_policy_overrides_defaults() {
        let command = test_command(protocol::UiCommand::ChatStreamEnd(json!({
            "message_id": "assistant-1",
            "stream_id": "stream-1",
            "final_sequence": 4,
            "content": [],
            "metadata": { "attention_policy": "none" }
        })));
        assert_eq!(activation_policy(&command), ActivationPolicy::NoActivate);
    }

    #[test]
    fn render_display_with_focus_target_requests_webview_focus() {
        let command = test_command(protocol::UiCommand::RenderDisplay(json!({
            "output_text": "Done",
            "metadata": { "focus_target": "content" }
        })));
        assert!(requests_webview_focus(&command));
    }

    #[test]
    fn render_display_with_display_presentation_initial_focus_requests_webview_focus() {
        let command = test_command(protocol::UiCommand::RenderDisplay(json!({
            "output_text": "Done",
            "metadata": {
                "display_presentation": {
                    "variant": "result_actions",
                    "initial_focus": "primary_action",
                    "toolbar": {
                        "actions": ["copy_text", "copy_markdown", "close"],
                        "placement": "after_content"
                    }
                }
            }
        })));
        assert!(requests_webview_focus(&command));
    }

    #[test]
    fn command_without_focus_target_does_not_request_webview_focus() {
        let command = test_command(protocol::UiCommand::UpdateProgress(json!({ "message": "Working..." })));
        assert!(!requests_webview_focus(&command));
    }
}
