import type { ConversationSummary } from '../protocol-types';
import {
	appState,
	ConversationSelectionState,
} from '../state.svelte';

export function evaluateSelectionState(): void {
	// Summaries may arrive later or omit a newly created empty conversation.
	// Only an authoritative selection command changes the active ID.
	if (!appState.chat.conversationId) {
		appState.chat.conversationSelectionState = appState.chat.conversations.length > 0
			? ConversationSelectionState.SummariesAvailable
			: ConversationSelectionState.None;
		return;
	}

	const hasMessages = appState.chat.transcript.count > 0;
	appState.chat.conversationSelectionState = hasMessages
		? ConversationSelectionState.SelectedLoaded
		: ConversationSelectionState.SelectedEmpty;
}

export function setConversationSummaries(conversations: ConversationSummary[] = []): void {
	const seen = new Set<string>();
	appState.chat.conversations = conversations.filter((c) => {
		if (!c.id || seen.has(c.id)) return false;
		seen.add(c.id);
		return true;
	});
	evaluateSelectionState();
}

export function setActiveConversationId(conversationId: string | null = null): void {
	const normalized = typeof conversationId === 'string' ? conversationId.trim() : '';
	appState.chat.conversationId = normalized || null;
	evaluateSelectionState();
}

export function syncActiveConversationSelection(): void {
	evaluateSelectionState();
}

export function resetChatState(): void {
	appState.chat.active = false;
	appState.chat.processing = false;
	appState.chat.requestId = null;
	appState.chat.latestRequestId = null;
	appState.chat.stopping = false;
	appState.chat.commandId = null;
	appState.chat.conversationId = null;
	appState.chat.conversationSelectionState = ConversationSelectionState.None;
	appState.chat.conversations = [];
	appState.chat.transcript.clear();
	appState.chat.attachments = [];
	appState.chat.composerText = '';
	appState.chat.latestCompletedMessageId = null;
}

const drafts = new Map<string, { text: string; attachments: typeof appState.chat.attachments }>();

export function saveChatDraft(): void {
	const id = appState.chat.conversationId;
	if (!id) return;
	if (!appState.chat.composerText && !appState.chat.attachments?.length) drafts.delete(id);
	else drafts.set(id, { text: appState.chat.composerText, attachments: [...appState.chat.attachments] });
}

export function restoreChatDraft(): void {
	const draft = drafts.get(appState.chat.conversationId || '');
	if (draft) {
		appState.chat.composerText = draft.text;
		appState.chat.attachments = [...draft.attachments];
	}
}

export function resetDisplayState(): void {
	appState.display.blocks = [];
	appState.display.actions = [];
	appState.display.variant = 'standard';
	appState.display.toolbarActions = [];
	appState.display.toolbarPlacement = 'after_content';
}

export function clearCurrentView(): void {
	resetChatState();
	resetDisplayState();
	appState.view.interactionMode = 'display';
	appState.view.mode = 'display';
	appState.view.pendingFocus = 'content';
}
