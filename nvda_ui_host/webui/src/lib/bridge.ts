import { addInitialImageAttachment } from './attachments';
import { renderDisplay } from './commands/render-display';
import { openChat } from './commands/open-chat';
import { syncSession } from './commands/sync-session';
import { setChatHistory, appendChatMessage, updateChatMessage } from './commands/chat-history';
import { beginChatStream, applyChatStreamDelta, endChatStream, abortChatStream } from './commands/chat-streaming';
import { showError, updateProgress, closeWindow } from './commands/error-progress-close';
import { reportUiFailure } from './commands/_shared';
import { updateControlState } from './operations/control-ops';
import { emitUiEvent } from './commands/_events';
import { COMMAND_REQUIRED_FIELDS, COMMAND_REQUIRED_FIELD_TYPES } from './protocol-commands';
import type {
	ChatSetHistoryPayload,
	ChatAppendPayload,
	ChatUpdatePayload,
	ChatStreamBeginPayload,
	ChatStreamDeltaPayload,
	ChatStreamEndPayload,
	ChatStreamAbortPayload,
	ShowErrorPayload,
	UpdateProgressPayload,
} from './protocol-types';
import type { CommandName, EventName, PayloadFieldType } from './protocol-commands';
import {
	appState,
	mergeLocalizedStrings,
	setStatus,
	t,
} from './state.svelte';

// ---------------------------------------------------------------------------
// Command dispatch table — add new commands here
// ---------------------------------------------------------------------------

type CommandHandler = (commandId: string, payload: unknown) => void;

function adaptHandler<T>(handler: (commandId: string, payload: T) => void): CommandHandler {
	return (commandId, payload) => handler(commandId, payload as T);
}

const COMMANDS: Record<CommandName, CommandHandler> = {
	health_check: () => {},
	render_display: adaptHandler(renderDisplay),
	open_chat: adaptHandler(openChat),
	sync_session: adaptHandler(syncSession),
	chat_set_history: adaptHandler<ChatSetHistoryPayload>(setChatHistory),
	chat_append: adaptHandler<ChatAppendPayload>(appendChatMessage),
	chat_update: adaptHandler<ChatUpdatePayload>(updateChatMessage),
	chat_stream_begin: adaptHandler<ChatStreamBeginPayload>(beginChatStream),
	chat_stream_delta: adaptHandler<ChatStreamDeltaPayload>(applyChatStreamDelta),
	chat_stream_end: adaptHandler<ChatStreamEndPayload>(endChatStream),
	chat_stream_abort: adaptHandler<ChatStreamAbortPayload>(abortChatStream),
	show_error: adaptHandler<ShowErrorPayload>(showError),
	update_progress: adaptHandler<UpdateProgressPayload>(updateProgress),
	close_window: () => {},
};

// Commands that should clear the status before executing
const CLEAR_STATUS_COMMANDS = new Set<CommandName>(['sync_session']);

// Commands that carry control state (providers, models, think mode, etc.).
// Content-only commands like chat_stream_delta do NOT trigger control extraction.
const CONTROL_COMMANDS = new Set<CommandName>([
	'open_chat',
	'sync_session',
	'render_display',
]);

// ---------------------------------------------------------------------------
// WebView bridge initialization
// ---------------------------------------------------------------------------

function ensureSendHostEvent(): boolean {
	if (typeof (window as any).__sendHostEvent !== 'function') {
		(window as any).__sendHostEvent = (payload: Record<string, unknown>) => {
			if ((window as any).chrome?.webview?.postMessage) {
				(window as any).chrome.webview.postMessage(JSON.stringify(payload));
				return true;
			} else {
				console.warn('Unable to send host event; WebView bridge unavailable.');
				return false;
			}
		};
	}
	return typeof (window as any).__sendHostEvent === 'function';
}

function matchesPayloadFieldType(value: unknown, expectedType: PayloadFieldType): boolean {
	switch (expectedType) {
		case 'string':
			return typeof value === 'string';
		case 'integer':
			return typeof value === 'number' && Number.isInteger(value);
		case 'boolean':
			return typeof value === 'boolean';
		case 'array':
			return Array.isArray(value);
		case 'object':
			return value !== null && typeof value === 'object' && !Array.isArray(value);
		case 'json':
			return true;
	}
}

function handleInboundCommand(envelope: Record<string, unknown>): void {
	const schema = envelope.schema;
	const version = envelope.version;
	const msgType = envelope.type;
	const command = envelope.command as Record<string, unknown> | undefined;

	if (schema !== 'nvda.ui_host' || version !== 2) {
		setStatus(
			t(
				'protocol_version_mismatch_status',
				`Protocol version mismatch. Expected nvda.ui_host v2, got ${schema} v${version}.`,
			),
			true,
		);
		emitUiEvent('ui_failed', (envelope.id as string) || null, {
			reason: `Protocol version mismatch: ${schema} v${version}`,
		});
		return;
	}

	if (msgType !== 'command' || !command?.name) {
		return;
	}

	const commandId = (envelope.id as string) || '';
	const commandName = command.name as string;
	const rawPayload = command.payload;
	const payload = (
		rawPayload && typeof rawPayload === 'object' && !Array.isArray(rawPayload) ? rawPayload : {}
	) as Record<string, unknown>;
	const requiredFields = COMMAND_REQUIRED_FIELDS[commandName as CommandName];
	if (!requiredFields) {
		const reason = `Unknown command: ${commandName}`;
		console.warn(reason);
		setStatus(t('unknown_command_status', reason), true);
		reportUiFailure(commandId, reason);
		return;
	}
	const missingFields = requiredFields.filter((field) => !(field in payload));
	if (missingFields.length > 0) {
		const reason = `Command ${commandName} is missing required fields: ${missingFields.join(', ')}`;
		console.warn(reason);
		setStatus(reason, true);
		reportUiFailure(commandId, reason);
		return;
	}
	const requiredTypes = COMMAND_REQUIRED_FIELD_TYPES[commandName as CommandName];
	const invalidTypes = Object.entries(requiredTypes).filter(
		([field, expectedType]) => !matchesPayloadFieldType(payload[field], expectedType),
	);
	if (invalidTypes.length > 0) {
		const reason = `Command ${commandName} has invalid field types: ${invalidTypes
			.map(([field, expectedType]) => `${field} (expected ${expectedType})`)
			.join(', ')}`;
		console.warn(reason);
		setStatus(reason, true);
		reportUiFailure(commandId, reason);
		return;
	}

	// Merge localized strings
	const localizedStrings = payload?.localized_strings || (payload?.metadata as Record<string, unknown>)?.localized_strings;
	if (localizedStrings && typeof localizedStrings === 'object') {
		mergeLocalizedStrings(localizedStrings as Record<string, string>);
	}

	// Store correlation for UI events
	appState.currentCommandId = commandId;

	// Clear status for certain commands
	if (CLEAR_STATUS_COMMANDS.has(commandName as CommandName)) {
		setStatus('');
	}

	// Apply control state (providers, models, think mode, etc.) from payload.
	// Only control-carrying commands trigger extraction — avoids wasted work
	// and noisy logs on content-only commands like chat_stream_delta.
	if (CONTROL_COMMANDS.has(commandName as CommandName)) {
		updateControlState(payload);
	}
	console.log(`[bridge] ${commandName} applied control: providers=${appState.control.availableProviders.length} models=${appState.control.availableModels.length} sel=${appState.control.selectedProvider}/${appState.control.selectedModel}`);

	const handler = COMMANDS[commandName as CommandName];
	if (handler) {
		try {
			handler(commandId, payload);
		} catch (error) {
			console.error(`Error handling command ${commandName}:`, error);
			reportUiFailure(commandId, `Handler error: ${String(error)}`);
		}
	} else {
		console.warn(`Unknown command: ${commandName}`);
		setStatus(
			t('unknown_command_status', `Unknown command: ${commandName}`),
			true,
		);
		reportUiFailure(commandId, `Unknown command: ${commandName}`);
	}
}

export function initializeWebViewBridge(): void {
	if (!ensureSendHostEvent()) {
		console.warn('WebView bridge transport unavailable.');
		return;
	}

	console.log('[bridge] WebView bridge initialized, ready for host commands');

	// Incoming messages from the Rust host are received by the
	// chrome.webview 'message' listener injected via AddScriptToExecuteOnDocumentCreated
	// (see webview.rs). That listener calls __receiveHostCommand, which we
	// define below. We intentionally do NOT add a second listener here to
	// avoid double-processing every command.

	(window as any).__receiveHostCommand = (json: string) => {
		try {
			const envelope = JSON.parse(json);
			if (envelope && typeof envelope === 'object') {
				handleInboundCommand(envelope as Record<string, unknown>);
			}
		} catch (error) {
			console.error('Failed to parse inbound host command:', error);
		}
	};

	// Re-export for use by actions.js
	(window as any).emitUiEvent = emitUiEvent;

	// Signal the Rust host that the WebView UI is ready to receive commands.
	// Without this event, the host never transitions to Ready state and
	// all queued commands (including sync_session with providers/models)
	// remain stuck in the queue forever.
	emitUiEvent('web_ui_ready', null, {});
}
