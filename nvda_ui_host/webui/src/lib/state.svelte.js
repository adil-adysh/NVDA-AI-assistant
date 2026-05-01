import { defaultLocalizedStrings } from './defaults.js';

function pingAnnouncer(message) {
    appState.announcerMessage = '';
    queueMicrotask(() => {
        appState.announcerMessage = message;
    });
}

export const appState = $state({
    currentCommandId: null,
    title: 'NVDA UI Host',
    statusMessage: defaultLocalizedStrings.waiting_status,
    announcerMessage: '',
    control: {
        availableProviders: [],
        availableModels: [],
        selectedProvider: '',
        selectedModel: '',
        thinkEnabled: false,
        providerDraft: '',
        modelDraft: '',
        thinkDraft: false,
        pendingChange: null,
    },
    localizedStrings: { ...defaultLocalizedStrings },
    chat: {
        active: false,
        commandId: null,
        conversationId: null,
        messages: [],
        attachments: [],
        composerText: '',
    },
    display: {
        blocks: [],
        actions: [],
    },
    view: {
        mode: 'display',
        pendingFocus: null,
    },
    copy: {
        text: '',
        markdown: '',
    },
});

export function t(key, fallback = '') {
    return appState.localizedStrings[key] || fallback;
}

export function mergeLocalizedStrings(payload) {
    const metadata = payload?.metadata || {};
    const nextStrings = payload?.localized_strings || metadata.localized_strings || {};

    if (nextStrings && typeof nextStrings === 'object') {
        Object.assign(appState.localizedStrings, nextStrings);
    }
}

export function setStatus(message, announce = false) {
    appState.statusMessage = message;

    if (announce) {
        pingAnnouncer(message);
    }
}

export function setPendingFocus(target) {
    appState.view.pendingFocus = target;
}

export function setViewMode(mode, pendingFocus = null) {
    appState.view.mode = mode;
    if (pendingFocus) {
        appState.view.pendingFocus = pendingFocus;
    }
}

export function setCopyBuffers(text = '', markdown = '') {
    appState.copy.text = text;
    appState.copy.markdown = markdown;
}

export function setDisplayBlocks(blocks = [], actions = []) {
    appState.display.blocks = blocks;
    appState.display.actions = actions;
}

export function resetDisplayState() {
    appState.display.blocks = [];
    appState.display.actions = [];
}

export function resetChatState() {
    appState.chat.active = false;
    appState.chat.commandId = null;
    appState.chat.conversationId = null;
    appState.chat.messages = [];
    appState.chat.attachments = [];
    appState.chat.composerText = '';
}

export function clearCurrentView() {
    resetChatState();
    resetDisplayState();
    setViewMode('display', 'content');
}

export function showDisplayText(text, focusTarget = null) {
    setDisplayBlocks(text ? [{ type: 'text', text }] : [], []);
    setViewMode('display', focusTarget);
}

export function setWindowTitle(title) {
    appState.title = title || 'NVDA UI Host';
}

export function setControlPending(change) {
    appState.control.pendingChange = change;
}

export function clearControlPending() {
    appState.control.pendingChange = null;
}
