import type { ChatSetHistoryPayload, ChatAppendPayload } from '../protocol-types';
import {
	setActiveConversationId,
	setConversationSummaries,
} from '../operations/view-ops';
import {
	appState,
	setViewMode,
} from '../state.svelte';
import {
	reportUiApplied,
	resolvePresentationFocusTarget,
	updateChatEnvelope,
} from './_shared';

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

	console.log(`[chat-history] transcript after upsert: ${appState.chat.transcript.count}`);

	const hasUserMessage = messages.some((m) => m.role === 'user');
	if (hasUserMessage) {
		appState.chat.composerText = '';
	}

	// Restore user's message in composer from error metadata so they can retry
	const meta = payload.metadata as Record<string, unknown> | undefined;
	if (typeof meta?.restore_text === 'string') {
		appState.chat.composerText = meta.restore_text;
	}

	setViewMode('chat', resolvePresentationFocusTarget(payload as Record<string, unknown>));
	reportUiApplied(commandId);
}
