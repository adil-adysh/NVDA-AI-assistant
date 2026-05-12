import type {
	ChatStreamBeginPayload,
	ChatStreamDeltaPayload,
	ChatStreamEndPayload,
	ChatStreamAbortPayload,
} from '../protocol-types';
import { appState, setViewMode } from '../state.svelte';
import { reportUiApplied, updateChatEnvelope } from './_shared';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getMessageId(payload: Record<string, unknown>): string {
	return (payload.message_id || payload.id || '') as string;
}

function getStreamId(payload: Record<string, unknown>): string {
	const sid = payload.stream_id as string;
	return typeof sid === 'string' && sid.trim() ? sid.trim() : '';
}

// ---------------------------------------------------------------------------
// chat_stream_begin
// ---------------------------------------------------------------------------

export function beginChatStream(commandId: string, payload: ChatStreamBeginPayload): void {
	const messageId = getMessageId(payload as Record<string, unknown>);
	const streamId = getStreamId(payload as Record<string, unknown>);
	if (!messageId || !streamId) return;

	updateChatEnvelope(payload as Record<string, unknown>);

	const existing = appState.chat.transcript.findById(messageId);
	if (!existing) {
		appState.chat.transcript.beginStream(
			messageId,
			streamId,
			(payload.role as string) || 'assistant',
			Array.isArray(payload.content) ? payload.content : [],
		);
	} else {
		appState.chat.transcript.beginStream(
			messageId,
			streamId,
			(payload.role as string) || existing.role || 'assistant',
			existing.streamId === streamId ? existing.content : [],
		);
	}

	setViewMode('chat');
	reportUiApplied(commandId);
}

// ---------------------------------------------------------------------------
// chat_stream_delta
// ---------------------------------------------------------------------------

export function applyChatStreamDelta(commandId: string, payload: ChatStreamDeltaPayload): void {
	const messageId = getMessageId(payload as Record<string, unknown>);
	const streamId = getStreamId(payload as Record<string, unknown>);
	const delta = typeof payload.delta === 'string' ? payload.delta : '';
	if (!messageId || !streamId || !delta) return;

	updateChatEnvelope(payload as Record<string, unknown>);

	const sequence = Number.isInteger(payload.sequence) ? payload.sequence : 0;
	const applied = appState.chat.transcript.applyDelta(messageId, streamId, delta, sequence);
	if (!applied) return;

	setViewMode('chat');
	reportUiApplied(commandId);
}

// ---------------------------------------------------------------------------
// chat_stream_end
// ---------------------------------------------------------------------------

export function endChatStream(commandId: string, payload: ChatStreamEndPayload): void {
	const messageId = getMessageId(payload as Record<string, unknown>);
	const streamId = getStreamId(payload as Record<string, unknown>);
	if (!messageId || !streamId) return;

	updateChatEnvelope(payload as Record<string, unknown>);
	appState.chat.transcript.endStream(messageId, streamId);
	reportUiApplied(commandId);
}

// ---------------------------------------------------------------------------
// chat_stream_abort
// ---------------------------------------------------------------------------

export function abortChatStream(commandId: string, payload: ChatStreamAbortPayload): void {
	const messageId = getMessageId(payload as Record<string, unknown>);
	const streamId = getStreamId(payload as Record<string, unknown>);
	if (!messageId || !streamId) return;

	updateChatEnvelope(payload as Record<string, unknown>);
	appState.chat.transcript.abortStream(messageId, streamId);
	reportUiApplied(commandId);
}
