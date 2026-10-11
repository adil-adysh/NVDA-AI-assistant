import type { OpenChatPayload } from '../protocol-types';
import { addInitialImageAttachment } from '../attachments';
import {
	setActiveConversationId,
	setConversationSummaries,
	resetChatState,
	resetDisplayState,
	saveChatDraft, restoreChatDraft,
} from '../operations/view-ops';
import {
	appState,
	setCopyBuffers,
	setViewMode,
} from '../state.svelte';
import {
	applyPresentationState,
	readPresentationValue,
	reportUiApplied,
	resolvePresentationFocusTarget,
} from './_shared';

export function openChat(commandId: string, payload: OpenChatPayload): void {
	const preserveConversation = appState.chat.active &&
		(payload.conversation_id || null) === appState.chat.conversationId &&
		!!(payload.preserve_conversation
		?? (payload.metadata as Record<string, unknown>)?.preserve_conversation);
	if (!preserveConversation) {
		saveChatDraft();
		resetChatState();
	}
	resetDisplayState();
	appState.chat.active = true;
	appState.chat.commandId = commandId;
	setActiveConversationId(payload.conversation_id || null);
	if (!preserveConversation) restoreChatDraft();

	const summaries = readPresentationValue(payload, 'conversation_summaries');
	if (Array.isArray(summaries)) setConversationSummaries(summaries);

	addInitialImageAttachment(payload.initial_image_base64);

	if (typeof payload.initial_text === 'string' && payload.initial_text.length > 0) {
		appState.chat.composerText =
			typeof payload.initial_text === 'string' ? payload.initial_text : '';
	}
	setCopyBuffers('', '');
	applyPresentationState(payload as Record<string, unknown>, {
		controlsVisible: true,
		interactionMode: 'chat',
	});
	setViewMode('chat', resolvePresentationFocusTarget(payload as Record<string, unknown>, 'composer'));

	reportUiApplied(commandId);
}
