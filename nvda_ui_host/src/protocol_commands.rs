// Auto-generated protocol command and event enums.
//
// Generated from ``scripts/protocol.yaml`` by ``scripts/generate_protocol.py``.
// DO NOT EDIT BY HAND.

// Note: serde and serde_json are already in scope from the parent protocol.rs.

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CommandName {
    HealthCheck,
    RenderDisplay,
    OpenChat,
    SyncSession,
    ChatSetHistory,
    ChatAppend,
    ChatUpdate,
    ChatStreamBegin,
    ChatStreamDelta,
    ChatStreamEnd,
    ChatStreamAbort,
    ShowError,
    UpdateProgress,
    CloseWindow,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EventName {
    UiReady,
    UiApplied,
    UiFailed,
    WindowClosed,
    HostLog,
    ChatSubmitted,
    ChatAttachmentAdded,
    ChatClosed,
    ProviderSelected,
    ModelSelected,
    ThinkModeToggled,
    UiActionInvoked,
    CloseHost,
}

#[derive(Debug, Clone, PartialEq)]
pub enum UiCommand {
    HealthCheck,
    RenderDisplay(Value),
    OpenChat(Value),
    SyncSession(Value),
    ChatSetHistory(Value),
    ChatAppend(Value),
    ChatUpdate(Value),
    ChatStreamBegin(Value),
    ChatStreamDelta(Value),
    ChatStreamEnd(Value),
    ChatStreamAbort(Value),
    ShowError(Value),
    UpdateProgress(Value),
    CloseWindow(Value),
}

impl UiCommand {
    pub fn command_name(&self) -> CommandName {
        match self {
            UiCommand::HealthCheck => CommandName::HealthCheck,
            UiCommand::RenderDisplay(_) => CommandName::RenderDisplay,
            UiCommand::OpenChat(_) => CommandName::OpenChat,
            UiCommand::SyncSession(_) => CommandName::SyncSession,
            UiCommand::ChatSetHistory(_) => CommandName::ChatSetHistory,
            UiCommand::ChatAppend(_) => CommandName::ChatAppend,
            UiCommand::ChatUpdate(_) => CommandName::ChatUpdate,
            UiCommand::ChatStreamBegin(_) => CommandName::ChatStreamBegin,
            UiCommand::ChatStreamDelta(_) => CommandName::ChatStreamDelta,
            UiCommand::ChatStreamEnd(_) => CommandName::ChatStreamEnd,
            UiCommand::ChatStreamAbort(_) => CommandName::ChatStreamAbort,
            UiCommand::ShowError(_) => CommandName::ShowError,
            UiCommand::UpdateProgress(_) => CommandName::UpdateProgress,
            UiCommand::CloseWindow(_) => CommandName::CloseWindow,
        }
    }

    pub fn as_legacy_action(&self) -> &'static str {
        match self {
            UiCommand::HealthCheck => "health_check",
            UiCommand::RenderDisplay(_) => "display_result",
            UiCommand::OpenChat(_) => "open_chat",
            UiCommand::SyncSession(_) => "sync_session",
            UiCommand::ChatSetHistory(_) => "chat_set_history",
            UiCommand::ChatAppend(_) => "chat_append",
            UiCommand::ChatUpdate(_) => "chat_update",
            UiCommand::ChatStreamBegin(_) => "chat_stream_begin",
            UiCommand::ChatStreamDelta(_) => "chat_stream_delta",
            UiCommand::ChatStreamEnd(_) => "chat_stream_end",
            UiCommand::ChatStreamAbort(_) => "chat_stream_abort",
            UiCommand::ShowError(_) => "show_error",
            UiCommand::UpdateProgress(_) => "progress_update",
            UiCommand::CloseWindow(_) => "close_window",
        }
    }

    pub fn payload(&self) -> Value {
        match self {
            UiCommand::HealthCheck => Value::Object(Default::default()),
            UiCommand::RenderDisplay(payload) | UiCommand::OpenChat(payload) | UiCommand::SyncSession(payload) | UiCommand::ChatSetHistory(payload) | UiCommand::ChatAppend(payload) | UiCommand::ChatUpdate(payload) | UiCommand::ChatStreamBegin(payload) | UiCommand::ChatStreamDelta(payload) | UiCommand::ChatStreamEnd(payload) | UiCommand::ChatStreamAbort(payload) | UiCommand::ShowError(payload) | UiCommand::UpdateProgress(payload) | UiCommand::CloseWindow(payload) => payload.clone(),
        }
    }

    pub(crate) fn from_legacy_action(action: &str, payload: Value) -> Result<Self, crate::protocol::ProtocolError> {
        match action {
            "health_check" => Ok(UiCommand::HealthCheck),
            "display_result" => Ok(UiCommand::RenderDisplay(payload)),
            "open_chat" => Ok(UiCommand::OpenChat(payload)),
            "sync_session" => Ok(UiCommand::SyncSession(payload)),
            "show_error" => Ok(UiCommand::ShowError(payload)),
            "progress_update" => Ok(UiCommand::UpdateProgress(payload)),
            "close_window" => Ok(UiCommand::CloseWindow(payload)),
            _ => Err(crate::protocol::ProtocolError::new(
                crate::protocol::ProtocolErrorKind::UnsupportedCommand,
                None,
                format!("Unsupported action: {action}"),
            )),
        }
    }

    pub(crate) fn from_command_name(name: CommandName, payload: Value) -> Self {
        match name {
            CommandName::HealthCheck => UiCommand::HealthCheck,
            CommandName::RenderDisplay => UiCommand::RenderDisplay(payload),
            CommandName::OpenChat => UiCommand::OpenChat(payload),
            CommandName::SyncSession => UiCommand::SyncSession(payload),
            CommandName::ChatSetHistory => UiCommand::ChatSetHistory(payload),
            CommandName::ChatAppend => UiCommand::ChatAppend(payload),
            CommandName::ChatUpdate => UiCommand::ChatUpdate(payload),
            CommandName::ChatStreamBegin => UiCommand::ChatStreamBegin(payload),
            CommandName::ChatStreamDelta => UiCommand::ChatStreamDelta(payload),
            CommandName::ChatStreamEnd => UiCommand::ChatStreamEnd(payload),
            CommandName::ChatStreamAbort => UiCommand::ChatStreamAbort(payload),
            CommandName::ShowError => UiCommand::ShowError(payload),
            CommandName::UpdateProgress => UiCommand::UpdateProgress(payload),
            CommandName::CloseWindow => UiCommand::CloseWindow(payload),
        }
    }
}
