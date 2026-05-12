import type { ChatSetHistoryPayload, ChatAppendPayload } from '../protocol-types';
import { extractTextFromBlocks } from '../content';
import {
	setActiveConversationId,
	setConversationSummaries,
} from '../operations/view-ops';
import {
	announceResponse,
	appState,
	setViewMode,
} from '../state.svelte';
import {
	reportUiApplied,
	resolvePresentationFocusTarget,
	updateChatEnvelope,
} from './_shared';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function announceAssistantMessage(message: { role?: string; streaming?: boolean; content?: { type: string; text?: string }[] }): void {
	if (!message || message.role !== 'assistant' || message.streaming === true) return;
	const text = extractTextFromBlocks(message.content);
	if (text) announceResponse(text);
}

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

	for (const msg of messages) {
		announceAssistantMessage(msg as any);
	}

	const hasUserMessage = messages.some((m) => m.role === 'user');
	if (hasUserMessage) {
		appState.chat.composerText = '';
	}

	setViewMode('chat', resolvePresentationFocusTarget(payload as Record<string, unknown>));
	reportUiApplied(commandId);
}
