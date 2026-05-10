import { defaultLocalizedStrings } from './defaults.js';

function publishAnnouncement(channel, message) {
    const nextId = appState.accessibility.nextAnnouncementId + 1;
    appState.accessibility.nextAnnouncementId = nextId;
    appState.accessibility[channel] = {
        id: nextId,
        message,
    };
}

export const appState = $state({
    currentCommandId: null,
    title: 'NVDA UI Host',
    statusMessage: '',
    controlsVisible: true,
    accessibility: {
        nextAnnouncementId: 0,
        statusAnnouncement: null,
        responseAnnouncement: null,
    },
    control: {
        availableProviders: [],
        availableModels: [],
        selectedProvider: '',
        selectedModel: '',
        thinkEnabled: false,
        providerDraft: '',
        modelDraft: '',
        thinkDraft: false,
        chatEnabled: true,
        providerStatus: {
            state: 'ready',
            reason: null,
            canInfer: true,
            canListModels: true,
        },
        pendingChange: null,
    },
    localizedStrings: { ...defaultLocalizedStrings },
    chat: {
        active: false,
        commandId: null,
        conversationId: null,
        conversationSelectionState: 'none',
        conversations: [],
        messages: [],
        attachments: [],
        composerText: '',
        renderVersion: 0,
    },
    display: {
        blocks: [],
        actions: [],
        variant: 'standard',
        toolbarActions: [],
        toolbarPlacement: 'after_content',
    },
    view: {
        mode: 'display',
        pendingFocus: null,
        interactionMode: 'display',
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
        publishAnnouncement('statusAnnouncement', message);
    }
}

export function announceResponse(message) {
    if (typeof message !== 'string' || !message.trim()) {
        return;
    }

    publishAnnouncement('responseAnnouncement', message.trim());
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

export function setInteractionMode(mode) {
    appState.view.interactionMode = mode || 'display';
}

export function setCopyBuffers(text = '', markdown = '') {
    appState.copy.text = text;
    appState.copy.markdown = markdown;
}

export const ConversationSelectionState = {
    None: 'none',
    SummariesAvailable: 'summaries_available',
    SelectedEmpty: 'selected_empty',
    SelectedLoaded: 'selected_loaded',
};

function getConversationById(conversationId) {
    return appState.chat.conversations.find(conversation => conversation.id === conversationId) || null;
}

function evaluateConversationSelectionState() {
    const hasConversations = appState.chat.conversations.length > 0;
    const selectedConversation = typeof appState.chat.conversationId === 'string'
        ? getConversationById(appState.chat.conversationId)
        : null;

    if (!hasConversations) {
        appState.chat.conversationId = null;
        appState.chat.conversationSelectionState = ConversationSelectionState.None;
        return;
    }

    if (!selectedConversation) {
        appState.chat.conversationId = null;
        appState.chat.conversationSelectionState = ConversationSelectionState.SummariesAvailable;
        return;
    }

    const hasMessages = Array.isArray(appState.chat.messages) && appState.chat.messages.length > 0;
    appState.chat.conversationSelectionState = hasMessages
        ? ConversationSelectionState.SelectedLoaded
        : ConversationSelectionState.SelectedEmpty;
}

export function setChatMessages(messages = []) {
    appState.chat.messages = Array.isArray(messages) ? messages : [];
    evaluateConversationSelectionState();
}

export function setDisplayBlocks(blocks = [], actions = [], presentation = {}) {
    appState.display.blocks = blocks;
    appState.display.actions = actions;
    appState.display.variant = presentation.variant || 'standard';
    appState.display.toolbarActions = Array.isArray(presentation.toolbarActions) ? presentation.toolbarActions : [];
    appState.display.toolbarPlacement = presentation.toolbarPlacement || 'after_content';
}

export function bumpChatRenderVersion() {
    appState.chat.renderVersion += 1;
}

export function setConversationSummaries(conversations = []) {
    const normalizedConversations = Array.isArray(conversations) ? conversations : [];
    const seenConversationIds = new Set();
    appState.chat.conversations = normalizedConversations.filter(conversation => {
        const conversationId = typeof conversation?.id === 'string' ? conversation.id : null;
        if (!conversationId || seenConversationIds.has(conversationId)) {
            return false;
        }
        seenConversationIds.add(conversationId);
        return true;
    });
    evaluateConversationSelectionState();
}

export function setActiveConversationId(conversationId = null) {
    const normalizedConversationId = typeof conversationId === 'string' ? conversationId.trim() : '';
    appState.chat.conversationId = normalizedConversationId || null;
    evaluateConversationSelectionState();
}

export function syncActiveConversationSelection() {
    evaluateConversationSelectionState();
}

export function resetDisplayState() {
    appState.display.blocks = [];
    appState.display.actions = [];
    appState.display.variant = 'standard';
    appState.display.toolbarActions = [];
    appState.display.toolbarPlacement = 'after_content';
}

export function resetChatState() {
    appState.chat.active = false;
    appState.chat.commandId = null;
    appState.chat.conversationId = null;
    appState.chat.conversationSelectionState = ConversationSelectionState.None;
    appState.chat.conversations = [];
    appState.chat.messages = [];
    appState.chat.attachments = [];
    appState.chat.composerText = '';
    appState.chat.renderVersion = 0;
}

export function clearCurrentView() {
    resetChatState();
    resetDisplayState();
    setInteractionMode('display');
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

export function setControlsVisible(visible) {
    appState.controlsVisible = Boolean(visible);
}
