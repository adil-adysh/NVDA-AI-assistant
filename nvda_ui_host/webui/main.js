import {
    attachmentStripEl,
    attachFilesEl,
    chatInputEl,
    chatSendEl,
    clearButtonEl,
    closeWindowButtonEl,
    copyMarkdownButtonEl,
    copyTextButtonEl,
    contentEl,
    fileInputEl,
    modelInputEl,
    modelSelectEl,
    providerSelectEl,
    thinkToggleEl,
} from './dom.js';
import { handleFileSelection, removeAttachment } from './attachments.js';
import {
    handleHostEnvelope,
    handleGlobalShortcut,
    handleResultActionClick,
    requestCloseHost,
    setupWebViewBridge,
    submitChatMessage,
    submitModelSelectSelection,
    submitModelSelection,
    submitProviderSelection,
    submitThinkModeToggle,
} from './commands.js';
import { applyLocalizedStrings } from './localization.js';
import {
    clearChat,
    copyMessageMarkdown,
    copyMessageTable,
    copyMessageText,
    getCurrentCopyMarkdown,
    getCurrentCopyText,
} from './rendering.js';
import { appState } from './state.js';
import { copyToClipboard, setStatus } from './utils.js';

chatSendEl?.addEventListener('click', submitChatMessage);
attachFilesEl?.addEventListener('click', () => fileInputEl?.click());
fileInputEl?.addEventListener('change', handleFileSelection);
providerSelectEl?.addEventListener('change', submitProviderSelection);
modelSelectEl?.addEventListener('change', submitModelSelectSelection);
modelInputEl?.addEventListener('change', submitModelSelection);
modelInputEl?.addEventListener('blur', submitModelSelection);
thinkToggleEl?.addEventListener('change', submitThinkModeToggle);
chatInputEl?.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submitChatMessage();
    }
});

contentEl?.addEventListener('click', event => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
        return;
    }

    const copyTextButton = target.closest('[data-copy-message-text]');
    if (copyTextButton instanceof HTMLElement) {
        copyMessageText(copyTextButton.dataset.copyMessageText || '');
        return;
    }

    const copyMarkdownButton = target.closest('[data-copy-message-markdown]');
    if (copyMarkdownButton instanceof HTMLElement) {
        copyMessageMarkdown(copyMarkdownButton.dataset.copyMessageMarkdown || '');
        return;
    }

    const copyTableButton = target.closest('[data-copy-message-table]');
    if (copyTableButton instanceof HTMLElement) {
        copyMessageTable(copyTableButton.dataset.copyMessageTable || '');
        return;
    }

    const actionButton = target.closest('[data-action-id]');
    if (actionButton instanceof HTMLElement) {
        handleResultActionClick(actionButton);
    }
});

attachmentStripEl?.addEventListener('click', event => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
        return;
    }

    const attachmentId = target.dataset.removeAttachment;
    if (attachmentId) {
        removeAttachment(attachmentId);
    }
});

copyTextButtonEl.onclick = () => copyToClipboard(getCurrentCopyText());
copyMarkdownButtonEl.onclick = () => copyToClipboard(getCurrentCopyMarkdown());
clearButtonEl.onclick = () => {
    clearChat();
    setStatus(appState.localizedStrings.content_cleared_status || 'Content cleared.');
};
closeWindowButtonEl.onclick = () => requestCloseHost();
document.addEventListener('keydown', handleGlobalShortcut);

setupWebViewBridge();
applyLocalizedStrings({ localized_strings: appState.localizedStrings });
