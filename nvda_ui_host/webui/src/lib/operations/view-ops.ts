import type { ConversationSummary } from '../protocol-types';
import {
	appState,
	ConversationSelectionState,
} from '../state.svelte';

function getConversationById(conversationId: string | null): ConversationSummary | null {
	if (!conversationId) return null;
	return appState.chat.conversations.find((c) => c.id === conversationId) ?? null;
}

export function evaluateSelectionState(): void {
	const hasConversations = appState.chat.conversations.length > 0;
	const selected = getConversationById(appState.chat.conversationId);

	if (!hasConversations) {
		appState.chat.conversationId = null;
		appState.chat.conversationSelectionState = ConversationSelectionState.None;
		return;
	}

	if (!selected) {
		appState.chat.conversationId = null;
		appState.chat.conversationSelectionState =
			ConversationSelectionState.SummariesAvailable;
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
	appState.chat.commandId = null;
	appState.chat.conversationId = null;
	appState.chat.conversationSelectionState = ConversationSelectionState.None;
	appState.chat.conversations = [];
	appState.chat.transcript.clear();
	appState.chat.attachments = [];
	appState.chat.composerText = '';
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
