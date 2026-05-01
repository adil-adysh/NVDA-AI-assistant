import { appState, clearCurrentView, setPendingFocus, setStatus, t } from './state.svelte.js';
import { clearPendingAttachments } from './attachments.js';
import {
    extractMarkdownFromBlocks,
    extractTextFromBlocks,
    formatRoleLabel,
    getCurrentCopyMarkdown,
    getCurrentCopyText,
    hasRenderedTables,
    normalizeContentBlocks,
    tableHtmlToMarkdown,
} from './content.js';
import { emitUiEvent } from './bridge.js';

async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        setStatus(t('copied_status', 'Copied to clipboard.'), true);
    } catch (error) {
        setStatus(t('copy_failed_status', 'Copy failed.'), true);
        console.error(error);
    }
}

function getAssistantTableMarkdown(message) {
    const htmlBlock = normalizeContentBlocks(message?.content)
        .find(block => block?.type === 'html' && /<table[\s>]/i.test(block.html || ''));

    return htmlBlock ? tableHtmlToMarkdown(htmlBlock.html || '') : '';
}

export function copyCurrentText() {
    return copyToClipboard(getCurrentCopyText());
}

export function copyCurrentMarkdown() {
    return copyToClipboard(getCurrentCopyMarkdown());
}

export function copyMessageText(message) {
    if (!message) {
        return;
    }

    return copyToClipboard(extractTextFromBlocks(message.content));
}

export function copyMessageMarkdown(message) {
    if (!message) {
        return;
    }

    const roleLabel = formatRoleLabel(message.role || 'assistant');
    const markdown = `##### ${roleLabel}\n\n${extractMarkdownFromBlocks(message.content)}`.trim();
    return copyToClipboard(markdown);
}

export function copyMessageTable(message) {
    if (!message || !hasRenderedTables(message.content)) {
        setStatus(t('copy_failed_status', 'Copy failed.'), true);
        return;
    }

    const markdown = getAssistantTableMarkdown(message);
    if (!markdown) {
        setStatus(t('copy_failed_status', 'Copy failed.'), true);
        return;
    }

    return copyToClipboard(markdown);
}

export function clearDisplayedContent() {
    clearCurrentView();
    setStatus(t('content_cleared_status', 'Content cleared.'), true);
}

export function requestCloseHost() {
    emitUiEvent('close_host', null);
}

export function submitChatMessage(fileInputElement = null) {
    const message = appState.chat.composerText.trim();
    const attachments = Array.isArray(appState.chat.attachments) ? appState.chat.attachments : [];

    if (!message && attachments.length === 0) {
        return;
    }

    emitUiEvent('chat_submitted', appState.chat.commandId, {
        conversation_id: appState.chat.conversationId,
        message,
        attachments,
    });

    appState.chat.composerText = '';
    clearPendingAttachments(fileInputElement);
    setStatus(t('submitted_status', 'Message submitted.'), true);
}

export function submitProviderSelection(provider) {
    const value = provider.trim();
    if (!value) {
        return;
    }

    appState.control.selectedProvider = value;
    emitUiEvent('provider_selected', appState.currentCommandId, { provider: value });
}

export function submitModelSelection(model) {
    const value = model.trim();
    if (!value) {
        return;
    }

    appState.control.selectedModel = value;
    emitUiEvent('model_selected', appState.currentCommandId, {
        provider: appState.control.selectedProvider.trim() || null,
        model: value,
    });
}

export function submitThinkModeToggle(enabled) {
    appState.control.thinkEnabled = Boolean(enabled);
    emitUiEvent('think_mode_toggled', appState.currentCommandId, { enabled: Boolean(enabled) });
}

export function invokeResultAction(action) {
    if (!action?.id) {
        return;
    }

    emitUiEvent('ui_action_invoked', appState.currentCommandId, {
        action_id: action.id,
        payload: action.payload || {},
    });
}

export function focusContentRegion() {
    setPendingFocus('content');
}

export function focusChatComposer() {
    setPendingFocus('composer');
}
