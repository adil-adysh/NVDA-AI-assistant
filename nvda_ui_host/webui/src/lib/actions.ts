import { clearPendingAttachments } from './attachments';
import { emitUiEvent } from './commands/_events';
import { invalidatePresentationFocus } from './commands/_shared';
import {
	extractMarkdownFromBlocks,
	extractTextFromBlocks,
	formatRoleLabel,
	getCurrentCopyMarkdown,
	getCurrentCopyText,
	hasRenderedTables,
	normalizeContentBlocks,
	tableHtmlToMarkdown,
} from './content';
import {
	clearCurrentView,
	setActiveConversationId,
} from './operations/view-ops';
import {
	appState,
	setControlPending,
	setPendingFocus,
	setStatus,
	t,
} from './state.svelte';

// ---------------------------------------------------------------------------
// Clipboard helpers
// ---------------------------------------------------------------------------

function fallbackCopyText(text: string): boolean {
	const previousFocus = document.activeElement as HTMLElement | null;
	const element = document.createElement('textarea');
	element.value = text;
	element.setAttribute('readonly', 'true');
	element.style.position = 'fixed';
	element.style.top = '-9999px';
	element.style.left = '-9999px';
	document.body.appendChild(element);
	element.focus();
	element.select();

	try {
		return document.execCommand('copy');
	} finally {
		document.body.removeChild(element);
		if (previousFocus?.isConnected) previousFocus.focus();
	}
}

async function copyToClipboard(text: string): Promise<boolean> {
	const normalizedText = String(text || '');
	if (!normalizedText.trim()) {
		setStatus(t('copy_failed_status', 'Copy failed.'), true);
		return false;
	}

	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(normalizedText);
		} else if (!fallbackCopyText(normalizedText)) {
			throw new Error('Clipboard API unavailable');
		}
		setStatus(t('copied_status', 'Copied to clipboard.'), true);
		return true;
	} catch (error) {
		try {
			if (fallbackCopyText(normalizedText)) {
				setStatus(t('copied_status', 'Copied to clipboard.'), true);
				return true;
			}
		} catch (fallbackError) {
			console.error(fallbackError);
		}
		setStatus(t('copy_failed_status', 'Copy failed.'), true);
		console.error(error);
		return false;
	}
}

function getAssistantTableMarkdown(message: { content?: { type: string; html?: string }[] }): string {
	const htmlBlock = normalizeContentBlocks(message?.content).find(
		(block) => block.type === 'html' && /<table[\s>]/i.test((block as { html?: string }).html || ''),
	);

	return htmlBlock ? tableHtmlToMarkdown((htmlBlock as { html: string }).html || '') : '';
}

// ---------------------------------------------------------------------------
// Public actions
// ---------------------------------------------------------------------------

export function copyCurrentText(): Promise<boolean> {
	return copyToClipboard(getCurrentCopyText());
}

export function copyCurrentMarkdown(): Promise<boolean> {
	return copyToClipboard(getCurrentCopyMarkdown());
}

export function copyMessageText(message: { role?: string; content?: { type: string; text?: string }[] }): void {
	if (!message) return;
	copyToClipboard(extractTextFromBlocks(message.content));
}

export function copyMessageMarkdown(message: { role?: string; content?: { type: string; text?: string }[] }): void {
	if (!message) return;
	const roleLabel = formatRoleLabel(message.role || 'assistant');
	const markdown = `##### ${roleLabel}\n\n${extractMarkdownFromBlocks(message.content)}`.trim();
	copyToClipboard(markdown);
}

export function copyMessageTable(message: { content?: { type: string; html?: string }[] }): void {
	if (!message || !hasRenderedTables(message.content)) {
		setStatus(t('copy_failed_status', 'Copy failed.'), true);
		return;
	}

	const markdown = getAssistantTableMarkdown(message);
	if (!markdown) {
		setStatus(t('copy_failed_status', 'Copy failed.'), true);
		return;
	}

	copyToClipboard(markdown);
}

export function clearDisplayedContent(): void {
	clearCurrentView();
	setStatus(t('content_cleared_status', 'Content cleared.'), true);
}

export function requestCloseHost(): void {
	invalidatePresentationFocus();
	emitUiEvent('close_host', null);
}

export function submitChatMessage(fileInputElement: HTMLInputElement | null = null): void {
	if (!appState.control.chatEnabled || appState.control.pendingChange || appState.chat.processing) return;

	const message = appState.chat.composerText.trim();
	const attachments = Array.isArray(appState.chat.attachments) ? appState.chat.attachments : [];

	if (!message && attachments.length === 0) return;
	const requestId = crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;

	const sent = emitUiEvent('chat_submitted', appState.chat.commandId, {
		conversation_id: appState.chat.conversationId,
		message,
		attachments,
		request_id: requestId,
	});

	if (!sent) return;

	appState.chat.composerText = '';
	appState.chat.processing = true;
	appState.chat.requestId = requestId;
	appState.chat.latestRequestId = requestId;
	appState.chat.stopping = false;
	clearPendingAttachments(fileInputElement);
	setStatus(t('submitted_status', 'Message sent. Processing.'), true);
}

export function stopChatResponse(): void {
	if (!appState.chat.processing || appState.chat.stopping || !appState.chat.requestId) return;
	if (!emitUiEvent('ui_action_invoked', appState.currentCommandId, {
		action_id: 'chat_stop',
		payload: { request_id: appState.chat.requestId, conversation_id: appState.chat.conversationId },
	})) {
		setStatus(t('send_failed_status', 'Unable to send request. The host connection is unavailable.'), true);
		return;
	}
	appState.chat.stopping = true;
	setStatus(t('stopping_status', 'Stopping response...'), true);
}

export function submitProviderSelection(provider: string): void {
	const value = provider.trim();
	if (!value || appState.control.pendingChange || value === appState.control.selectedProvider) return;

	const previousModelDraft = appState.control.modelDraft;
	appState.control.modelDraft = '';
	setControlPending('provider');
	setStatus(t('provider_switching_status', 'Switching provider...'));
	if (!emitUiEvent('provider_selected', appState.currentCommandId, { provider: value })) {
		appState.control.providerDraft = appState.control.selectedProvider;
		appState.control.modelDraft = previousModelDraft;
		setControlPending(null);
		setStatus(t('send_failed_status', 'Unable to send request. The host connection is unavailable.'), true);
	}
}

export function submitModelSelection(model: string): void {
	const value = model.trim();
	if (
		!value ||
		appState.control.pendingChange ||
		(value === appState.control.selectedModel && appState.control.providerDraft === appState.control.selectedProvider)
	) {
		return;
	}

	setControlPending('model');
	setStatus(t('model_switching_status', 'Updating model...'));
	if (!emitUiEvent('model_selected', appState.currentCommandId, {
		provider: appState.control.selectedProvider.trim() || null,
		model: value,
	})) {
		setControlPending(null);
		setStatus(t('send_failed_status', 'Unable to send request. The host connection is unavailable.'), true);
	}
}

export function submitThinkModeToggle(enabled: boolean): void {
	if (appState.control.pendingChange || enabled === appState.control.thinkEnabled) return;

	setControlPending('think');
	setStatus(t('think_mode_updating_status', 'Updating think mode...'));
	if (!emitUiEvent('think_mode_toggled', appState.currentCommandId, { enabled })) {
		appState.control.thinkDraft = appState.control.thinkEnabled;
		setControlPending(null);
		setStatus(t('send_failed_status', 'Unable to send request. The host connection is unavailable.'), true);
	}
}

export function invokeResultAction(action: { id?: string; payload?: Record<string, unknown> }): void {
	if (!action?.id) return;

	emitUiEvent('ui_action_invoked', appState.currentCommandId, {
		action_id: action.id,
		payload: action.payload || {},
	});
}

export function startNewConversation(): void {
	emitUiEvent('ui_action_invoked', appState.currentCommandId, {
		action_id: 'conversation_new',
		payload: {},
	});
}

export function openConversation(conversationId: string): void {
	if (!conversationId) return;
	if (emitUiEvent('ui_action_invoked', appState.currentCommandId, {
		action_id: 'conversation_open',
		payload: { conversation_id: conversationId },
	})) {
		setActiveConversationId(conversationId);
	} else {
		setStatus(t('send_failed_status', 'Unable to send request. The host connection is unavailable.'), true);
	}
}

export function deleteConversation(conversationId: string): void {
	if (!conversationId) return;
	emitUiEvent('ui_action_invoked', appState.currentCommandId, {
		action_id: 'conversation_delete',
		payload: { conversation_id: conversationId },
	});
}

export function focusContentRegion(): void {
	setPendingFocus('content');
}

export function focusChatComposer(): void {
	setPendingFocus('composer');
}

export function focusProviderSelect(): void {
	const el = document.getElementById('provider-select');
	if (el) {
		(el as HTMLElement).focus();
	}
}

export function focusModelSelect(): void {
	const el = document.getElementById('model-select');
	if (el) {
		(el as HTMLElement).focus();
	}
}
