// Protocol payload types matching nvda_ui_host/src/protocol.rs and
// addon/globalPlugins/AI-assistant/ui/host_protocol.py.
//
// These are the single source of truth for WebView-side payload shapes.
// Keep additive — the host and Python side must stay compatible.

// Re-export canonical command/event names from the generated spec.
export type { CommandName, EventName } from './protocol-commands';
export { CHAT_COMMANDS } from './protocol-commands';

// ---------------------------------------------------------------------------
// Common / shared
// ---------------------------------------------------------------------------

export interface ProtocolEnvelope {
	schema: string;
	version: number;
	id: string;
	correlation_id: string | null;
	source: 'nvda_addon' | 'ui_host' | 'web_ui';
	type: 'command' | 'event' | 'ack' | 'error';
}

export interface CommandEnvelope extends ProtocolEnvelope {
	type: 'command';
	command: {
		name: string;
		payload: Record<string, unknown>;
	};
}

export interface EventEnvelope extends ProtocolEnvelope {
	type: 'event';
	event: {
		name: string;
		payload: Record<string, unknown>;
	};
}

// ---------------------------------------------------------------------------
// Presentation metadata (shared across commands)
// ---------------------------------------------------------------------------

export interface PresentationMetadata {
	controls_visible?: boolean;
	interaction_mode?: 'display' | 'chat';
	focus_target?: string;
	status_message?: string;
	localized_strings?: Record<string, string>;
	actions?: ResultAction[];
	conversation_summaries?: ConversationSummary[];
	provider_state?: { provider?: string; model?: string };
	provider_status?: ProviderStatus;
	available_providers?: (string | ProviderOption)[];
	available_models?: string[];
	think_enabled?: boolean;
	chat_enabled?: boolean;
	display_presentation?: DisplayPresentation;
	attention_policy?: string;
}

export interface DisplayPresentation {
	variant?: 'standard' | 'result_actions';
	toolbar?: { placement?: string; actions?: string[] };
	initial_focus?: string;
}

export interface ProviderStatus {
	state?: string;
	reason?: string | null;
	can_infer?: boolean;
	can_list_models?: boolean;
}

export interface ProviderOption {
	id?: string;
	value?: string;
	label?: string;
}

export interface ResultAction {
	id: string;
	label?: string;
	kind?: string | null;
	payload?: Record<string, unknown> | null;
}

export interface ConversationSummary {
	id: string;
	title?: string;
	preview?: string;
}

// ---------------------------------------------------------------------------
// Content blocks
// ---------------------------------------------------------------------------

export interface TextBlock {
	type: 'text';
	text: string;
}

export interface HtmlBlock {
	type: 'html';
	html: string;
}

export interface ThinkingBlock {
	type: 'thinking';
	text: string;
	summary?: string;
	collapsed?: boolean;
}

export interface ImageBlock {
	type: 'image';
	image_base64?: string;
	mime_type?: string;
	alt?: string;
}

export interface ErrorBlock {
	type: 'error';
	text: string;
	summary?: string;
	is_internal?: boolean;
}

export type ContentBlock = TextBlock | HtmlBlock | ThinkingBlock | ImageBlock | ErrorBlock;

// ---------------------------------------------------------------------------
// Chat messages
// ---------------------------------------------------------------------------

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant' | 'system';
	content: ContentBlock[];
	streaming?: boolean;
	streamId?: string | null;
	streamSequence?: number;
	streamAborted?: boolean;
}

// ---------------------------------------------------------------------------
// Attachment
// ---------------------------------------------------------------------------

export interface Attachment {
	id: string;
	name?: string;
	kind?: 'image' | 'text';
	image_base64?: string;
	mime_type?: string;
	text_content?: string;
}

// ---------------------------------------------------------------------------
// Command payloads
// ---------------------------------------------------------------------------

export interface RenderDisplayPayload {
	use_case_id?: string | null;
	title?: string;
	success?: boolean;
	message?: string | null;
	output_text?: string | null;
	output_html?: string | null;
	is_html?: boolean;
	is_browseable?: boolean;
	close_button?: boolean;
	copy_button?: boolean;
	copy_text?: string | null;
	copy_markdown?: string | null;
	thinking_trace?: string | null;
	thinking_summary?: string | null;
	thinking_visible_by_default?: boolean;
	actions?: ResultAction[];
	metadata?: PresentationMetadata;
}

export interface OpenChatPayload {
	conversation_id?: string | null;
	initial_text?: string;
	initial_image_base64?: string;
	preserve_conversation?: boolean;
	metadata?: PresentationMetadata;
}

export interface SyncSessionPayload {
	conversation_id?: string | null;
	metadata?: PresentationMetadata;
}

export interface ChatSetHistoryPayload {
	conversation_id?: string;
	command_id?: string;
	messages: ChatMessage[];
	metadata?: PresentationMetadata;
}

export interface ChatAppendPayload {
	conversation_id?: string;
	command_id?: string;
	message?: ChatMessage;
	messages?: ChatMessage[];
	metadata?: PresentationMetadata;
}

export interface ChatUpdatePayload {
	conversation_id?: string;
	command_id?: string;
	message_id: string;
	message?: Partial<ChatMessage>;
	metadata?: PresentationMetadata;
}

export interface ChatStreamBeginPayload {
	message_id: string;
	id?: string;
	stream_id: string;
	role?: string;
	content?: ContentBlock[];
	conversation_id?: string;
	command_id?: string;
	metadata?: PresentationMetadata;
}

export interface ChatStreamDeltaPayload {
	message_id: string;
	id?: string;
	stream_id: string;
	delta: string;
	sequence: number;
	conversation_id?: string;
	command_id?: string;
	metadata?: PresentationMetadata;
}

export interface ChatStreamEndPayload {
	message_id: string;
	id?: string;
	stream_id: string;
	content?: ContentBlock[];
	answer_section?: ContentBlock[];
	conversation_id?: string;
	command_id?: string;
	metadata?: PresentationMetadata;
}

export interface ChatStreamAbortPayload {
	message_id: string;
	id?: string;
	stream_id: string;
	reason?: string;
	conversation_id?: string;
	command_id?: string;
	metadata?: PresentationMetadata;
}

export interface ShowErrorPayload {
	title?: string;
	message: string;
	metadata?: PresentationMetadata;
}

export interface UpdateProgressPayload {
	title?: string;
	message: string;
	progress?: number;
	metadata?: PresentationMetadata;
}

export interface CloseWindowPayload {
	metadata?: PresentationMetadata;
}
