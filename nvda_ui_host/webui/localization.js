import {
    attachFilesEl,
    chatInputEl,
    chatSendEl,
    modelLabelEl,
    providerLabelEl,
    thinkModeLabelEl,
} from './dom.js';
import { appState } from './state.js';

function getToolbarRefs() {
    return {
        copyTextButton: document.getElementById('copy-text'),
        copyMarkdownButton: document.getElementById('copy-markdown'),
        clearButton: document.getElementById('clear'),
        closeButton: document.getElementById('close-window'),
    };
}

export function t(key, fallback = '') {
    return appState.localizedStrings[key] || fallback;
}

export function applyLocalizedStrings(payload) {
    const metadata = payload?.metadata || {};
    const nextStrings = payload?.localized_strings || metadata.localized_strings || {};
    if (nextStrings && typeof nextStrings === 'object') {
        Object.assign(appState.localizedStrings, nextStrings);
    }

    if (providerLabelEl) {
        providerLabelEl.textContent = t('provider_label', 'Provider');
    }
    if (modelLabelEl) {
        modelLabelEl.textContent = t('model_label', 'Model');
    }
    if (thinkModeLabelEl) {
        thinkModeLabelEl.textContent = t('think_mode_label', 'Think mode');
    }
    if (attachFilesEl) {
        attachFilesEl.textContent = t('attach_button', 'Attach');
    }
    if (chatSendEl) {
        chatSendEl.textContent = t('send_button', 'Send');
    }
    if (chatInputEl) {
        chatInputEl.placeholder = t('chat_placeholder', 'Type your message...');
    }

    const { copyTextButton, copyMarkdownButton, clearButton, closeButton } = getToolbarRefs();
    if (copyTextButton) {
        copyTextButton.textContent = t('copy_text_button', 'Copy text');
    }
    if (copyMarkdownButton) {
        copyMarkdownButton.textContent = t('copy_markdown_button', 'Copy markdown');
    }
    if (clearButton) {
        clearButton.textContent = t('clear_button', 'Clear');
    }
    if (closeButton) {
        closeButton.textContent = t('close_button', 'Close');
    }
}
