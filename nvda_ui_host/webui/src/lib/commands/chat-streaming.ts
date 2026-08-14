import type {
	ChatStreamBeginPayload,
	ChatStreamDeltaPayload,
	ChatStreamEndPayload,
	ChatStreamAbortPayload,
} from '../protocol-types';
import { announceResponse, appState, setViewMode, setStatus, t } from '../state.svelte';
import { summarizeForAnnouncement } from '../content';
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

	// If the Python side computed HTML blocks (via `_build_assistant_content_blocks`),
	// the final structured content is carried in `payload.content` or `payload.answer_section`.
	// Pass it to endStream so the placeholder text-delta content is replaced by
	// the authoritative HTML blocks — making old messages and new streamed messages
	// render identically with proper HTML formatting.
	const finalContent =
		Array.isArray(payload.content) && payload.content.length > 0
			? payload.content
			: Array.isArray(payload.answer_section) && payload.answer_section.length > 0
				? payload.answer_section
				: undefined;

	const ended = appState.chat.transcript.endStream(messageId, streamId, finalContent);
	if (ended) {
		appState.chat.processing = false;
		const message = appState.chat.transcript.findById(messageId);
		const summary = summarizeForAnnouncement(message?.content);
		announceResponse(
			summary
				? `${t('response_complete', 'Response complete')}: ${summary}`
				: t('response_complete', 'Response complete.'),
		);
		setStatus(t('response_ready_status', 'Response ready.'), false);
	}
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
	appState.chat.processing = false;
	reportUiApplied(commandId);
}
