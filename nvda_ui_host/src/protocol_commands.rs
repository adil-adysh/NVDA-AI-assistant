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

    pub fn payload(&self) -> Value {
        match self {
            UiCommand::HealthCheck => Value::Object(Default::default()),
            UiCommand::RenderDisplay(payload) | UiCommand::OpenChat(payload) | UiCommand::SyncSession(payload) | UiCommand::ChatSetHistory(payload) | UiCommand::ChatAppend(payload) | UiCommand::ChatUpdate(payload) | UiCommand::ChatStreamBegin(payload) | UiCommand::ChatStreamDelta(payload) | UiCommand::ChatStreamEnd(payload) | UiCommand::ChatStreamAbort(payload) | UiCommand::ShowError(payload) | UiCommand::UpdateProgress(payload) | UiCommand::CloseWindow(payload) => payload.clone(),
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

pub fn required_payload_fields(command: &CommandName) -> &'static [&'static str] {
    match command {
        CommandName::HealthCheck => &[],
        CommandName::RenderDisplay => &["title"],
        CommandName::OpenChat => &["title"],
        CommandName::SyncSession => &[],
        CommandName::ChatSetHistory => &["conversation_id", "messages"],
        CommandName::ChatAppend => &["conversation_id", "message"],
        CommandName::ChatUpdate => &["conversation_id", "message_id", "content"],
        CommandName::ChatStreamBegin => &["message_id", "stream_id"],
        CommandName::ChatStreamDelta => &["message_id", "stream_id", "delta", "sequence"],
        CommandName::ChatStreamEnd => &["message_id", "stream_id", "final_sequence", "content"],
        CommandName::ChatStreamAbort => &["message_id", "stream_id", "last_sequence"],
        CommandName::ShowError => &["error_message"],
        CommandName::UpdateProgress => &["stage", "message"],
        CommandName::CloseWindow => &[],
    }
}

pub fn required_payload_types(command: &CommandName) -> &'static [(&'static str, &'static str)] {
    match command {
        CommandName::HealthCheck => &[],
        CommandName::RenderDisplay => &[("title", "string")],
        CommandName::OpenChat => &[("title", "string")],
        CommandName::SyncSession => &[],
        CommandName::ChatSetHistory => &[("conversation_id", "string"), ("messages", "array")],
        CommandName::ChatAppend => &[("conversation_id", "string"), ("message", "object")],
        CommandName::ChatUpdate => &[("conversation_id", "string"), ("message_id", "string"), ("content", "json")],
        CommandName::ChatStreamBegin => &[("message_id", "string"), ("stream_id", "string")],
        CommandName::ChatStreamDelta => &[("message_id", "string"), ("stream_id", "string"), ("delta", "string"), ("sequence", "integer")],
        CommandName::ChatStreamEnd => &[("message_id", "string"), ("stream_id", "string"), ("final_sequence", "integer"), ("content", "json")],
        CommandName::ChatStreamAbort => &[("message_id", "string"), ("stream_id", "string"), ("last_sequence", "integer")],
        CommandName::ShowError => &[("error_message", "string")],
        CommandName::UpdateProgress => &[("stage", "string"), ("message", "string")],
        CommandName::CloseWindow => &[],
    }
}
