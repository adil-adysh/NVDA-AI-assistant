import type { ChatSetHistoryPayload, ChatAppendPayload, ChatUpdatePayload } from '../protocol-types';
import {
	appState,
	setViewMode,
} from '../state.svelte';
import {
	reportUiApplied,
	isCurrentChatEvent,
	resolvePresentationFocusTarget,
	updateChatEnvelope,
} from './_shared';
import { completeChatTurn } from './chat-feedback';

// ---------------------------------------------------------------------------
// chat_set_history
// ---------------------------------------------------------------------------

export function setChatHistory(commandId: string, payload: ChatSetHistoryPayload): void {
	updateChatEnvelope(payload as Record<string, unknown>);
	const msgCount = Array.isArray(payload.messages) ? payload.messages.length : 0;
	console.log(`[chat-history] setChatHistory: ${msgCount} messages, sample: ${msgCount > 0 ? JSON.stringify(payload.messages[0]).slice(0,120) : 'empty'}`);
	appState.chat.transcript.setHistory(payload.messages);
	console.log(`[chat-history] transcript count after setHistory: ${appState.chat.transcript.count}`);
	setViewMode('chat', resolvePresentationFocusTarget(payload as Record<string, unknown>));
	reportUiApplied(commandId);
}

// ---------------------------------------------------------------------------
// chat_append
// ---------------------------------------------------------------------------

export function appendChatMessage(commandId: string, payload: ChatAppendPayload): void {
	if (!isCurrentChatEvent(payload as Record<string, unknown>)) { reportUiApplied(commandId); return; }
	updateChatEnvelope(payload as Record<string, unknown>);

	const messages = Array.isArray(payload.messages)
		? payload.messages
		: payload.message
			? [payload.message]
			: [payload as unknown as { id: string; role: string; content: { type: string; text?: string }[]; streaming?: boolean }];

	console.log(`[chat-history] appendChatMessage: ${messages.length} message(s), transcript before: ${appState.chat.transcript.count}`);

	for (const msg of messages) {
		appState.chat.transcript.upsert(msg as any);
	}
	for (const message of messages) {
		if (message.role === 'assistant' && !message.streaming) completeChatTurn(message.id, payload as Record<string, unknown>);
	}

	console.log(`[chat-history] transcript after upsert: ${appState.chat.transcript.count}`);

	// Restore user's message in composer from error metadata so they can retry
	const meta = payload.metadata as Record<string, unknown> | undefined;
	if (typeof meta?.restore_text === 'string' && !appState.chat.composerText) {
		appState.chat.composerText = meta.restore_text;
		if (!appState.chat.attachments?.length && Array.isArray(meta.restore_attachments)) appState.chat.attachments = meta.restore_attachments as typeof appState.chat.attachments;
	}

	setViewMode('chat', resolvePresentationFocusTarget(payload as Record<string, unknown>));
	reportUiApplied(commandId);
}

// ---------------------------------------------------------------------------
// chat_update
// ---------------------------------------------------------------------------

export function updateChatMessage(commandId: string, payload: ChatUpdatePayload): void {
	if (!isCurrentChatEvent(payload as Record<string, unknown>)) { reportUiApplied(commandId); return; }
	updateChatEnvelope(payload);
	const updated = appState.chat.transcript.updateMessage(payload.message_id, (message) => ({
		...message,
		...(payload.message ?? {}),
		...(payload.content !== undefined
			? { content: typeof payload.content === 'string' ? [{ type: 'text', text: payload.content }] : payload.content }
			: {}),
	}));
	if (updated) reportUiApplied(commandId);
}
