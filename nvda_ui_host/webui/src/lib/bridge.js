import { addInitialImageAttachment } from './attachments.js';
import {
    appState,
    bumpChatRenderVersion,
    clearControlPending,
    mergeLocalizedStrings,
    resetChatState,
    resetDisplayState,
    setCopyBuffers,
    setControlsVisible,
    setDisplayBlocks,
    setInteractionMode,
    setPendingFocus,
    setStatus,
    setViewMode,
    setWindowTitle,
    showDisplayText,
    t,
} from './state.svelte.js';

function ensureSendHostEvent() {
    if (typeof window.__sendHostEvent !== 'function') {
        window.__sendHostEvent = payload => {
            if (window.chrome?.webview?.postMessage) {
                window.chrome.webview.postMessage(JSON.stringify(payload));
            } else {
                console.warn('Unable to send host event; WebView bridge unavailable.');
            }
        };
    }
}

function getMetadata(payload) {
    return payload?.metadata || {};
}

function readPresentationValue(payload, key, fallback = undefined) {
    const metadata = getMetadata(payload);
    return payload?.[key] ?? metadata[key] ?? fallback;
}

function applyPresentationState(payload, defaults = {}) {
    const controlsVisible = readPresentationValue(payload, 'controls_visible', defaults.controlsVisible);
    if (typeof controlsVisible === 'boolean') {
        setControlsVisible(controlsVisible);
    }

    const interactionMode = readPresentationValue(payload, 'interaction_mode', defaults.interactionMode);
    if (typeof interactionMode === 'string' && interactionMode.trim()) {
        setInteractionMode(interactionMode.trim());
    }
}

const DISPLAY_VARIANTS = new Set(['standard', 'result_actions']);
const DISPLAY_TOOLBAR_ACTIONS = new Set(['copy_text', 'copy_markdown', 'clear', 'close']);

function resolveDisplayPresentation(payload, { hasActions = false } = {}) {
    const metadata = getMetadata(payload);
    const rawPresentation = payload?.display_presentation || metadata.display_presentation || {};
    const variant = typeof rawPresentation?.variant === 'string' && DISPLAY_VARIANTS.has(rawPresentation.variant)
        ? rawPresentation.variant
        : hasActions
        ? 'result_actions'
        : 'standard';
    const toolbar = rawPresentation?.toolbar && typeof rawPresentation.toolbar === 'object'
        ? rawPresentation.toolbar
        : {};
    const toolbarActions = Array.isArray(toolbar.actions)
        ? toolbar.actions.filter(action => typeof action === 'string' && DISPLAY_TOOLBAR_ACTIONS.has(action))
        : [];
    const initialFocus = resolvePresentationFocusTarget({
        ...payload,
        metadata: {
            ...metadata,
            focus_target: rawPresentation?.initial_focus ?? metadata.focus_target,
        },
    }, hasActions ? 'primary_action' : 'content');

    return {
        variant,
        initialFocus,
        toolbarActions,
        toolbarPlacement: toolbar.placement === 'after_content' ? 'after_content' : 'after_content',
    };
}

function updateChatEnvelopeState(payload) {
    appState.chat.active = true;
    if (payload.conversation_id) {
        appState.chat.conversationId = payload.conversation_id;
    }
    if (payload.command_id) {
        appState.chat.commandId = payload.command_id;
    }
}

function replaceMessageById(message) {
    if (message?.id) {
        appState.chat.messages = appState.chat.messages.filter(candidate => candidate.id !== message.id);
    }
    appState.chat.messages.push(message);
}

function setChatMessages(messages) {
    appState.chat.messages = Array.isArray(messages) ? messages : [];
    bumpChatRenderVersion();
}

function updateSingleChatMessage(messageId, updater) {
    appState.chat.messages = appState.chat.messages.map(message => (
        message.id === messageId ? updater(message) : message
    ));
    bumpChatRenderVersion();
}

function updateControlState(payload) {
    const providerState = readPresentationValue(payload, 'provider_state', {}) || {};
    const availableProviders = readPresentationValue(payload, 'available_providers');
    const availableModels = readPresentationValue(payload, 'available_models');
    const thinkEnabled = readPresentationValue(payload, 'think_enabled');

    if (Array.isArray(availableProviders)) {
        appState.control.availableProviders = availableProviders;
    }
    if (Array.isArray(availableModels)) {
        appState.control.availableModels = availableModels;
    }
    if (typeof providerState?.provider === 'string') {
        appState.control.selectedProvider = providerState.provider;
        appState.control.providerDraft = providerState.provider;
    }
    if (typeof providerState?.model === 'string') {
        appState.control.selectedModel = providerState.model;
        appState.control.modelDraft = providerState.model;
    }
    if (typeof thinkEnabled === 'boolean') {
        appState.control.thinkEnabled = thinkEnabled;
        appState.control.thinkDraft = thinkEnabled;
    }
    applyPresentationState(payload);

    if (
        Array.isArray(availableProviders) ||
        Array.isArray(availableModels) ||
        typeof providerState?.provider === 'string' ||
        typeof providerState?.model === 'string' ||
        typeof thinkEnabled === 'boolean'
    ) {
        clearControlPending();
    }
}

function getHostStatusMessage(payload) {
    const statusMessage = readPresentationValue(payload, 'status_message');
    return typeof statusMessage === 'string' && statusMessage.trim() ? statusMessage.trim() : '';
}

function resolvePresentationFocusTarget(payload, fallback = null) {
    const target = readPresentationValue(payload, 'focus_target', fallback);
    if (typeof target !== 'string' || !target.trim()) {
        return null;
    }

    return target.trim();
}

function reportUiApplied(commandId) {
    emitUiEvent('ui_applied', commandId);
}

function reportUiFailure(commandId, reason) {
    emitUiEvent('ui_failed', commandId, { reason });
}

function openChat(commandId, payload) {
    resetChatState();
    resetDisplayState();
    appState.chat.active = true;
    appState.chat.commandId = commandId;
    appState.chat.conversationId = payload.conversation_id || null;
    addInitialImageAttachment(payload.initial_image_base64);

    appState.chat.composerText = typeof payload.initial_text === 'string' ? payload.initial_text : '';
    setCopyBuffers('', '');
    applyPresentationState(payload, { controlsVisible: true, interactionMode: 'chat' });
    setViewMode('chat', resolvePresentationFocusTarget(payload, 'composer'));
}

function syncSession(payload) {
    applyPresentationState(payload, { controlsVisible: true, interactionMode: 'chat' });
    if (payload.conversation_id) {
        appState.chat.conversationId = payload.conversation_id;
    }
}

function renderDisplay(payload) {
    const actions = readPresentationValue(payload, 'actions', []);
    const thinkingTrace = readPresentationValue(payload, 'thinking_trace', null);
    const thinkingSummary = readPresentationValue(payload, 'thinking_summary', null);
    const thinkingCollapsed = readPresentationValue(payload, 'thinking_visible_by_default', true) === false;
    const blocks = [];
    const normalizedActions = Array.isArray(actions) ? actions : [];
    const displayPresentation = resolveDisplayPresentation(payload, { hasActions: normalizedActions.length > 0 });

    if (payload.output_html) {
        blocks.push({ type: 'html', html: payload.output_html });
    } else {
        blocks.push({ type: 'text', text: payload.output_text || payload.message || t('no_content', 'No content available.') });
    }

    if (thinkingTrace) {
        blocks.push({
            type: 'thinking',
            text: thinkingTrace,
            summary: thinkingSummary || t('thinking_label', 'Thinking'),
            collapsed: thinkingCollapsed,
        });
    }

    setDisplayBlocks(blocks, normalizedActions, displayPresentation);
    applyPresentationState(payload, { controlsVisible: true, interactionMode: 'display' });
    setViewMode('display');
    setPendingFocus(displayPresentation.initialFocus);
    setCopyBuffers(payload.copy_text || payload.output_text || '', payload.copy_markdown || '');
}

function setChatHistory(payload) {
    updateChatEnvelopeState(payload);
    setChatMessages(payload.messages);
    setViewMode('chat', resolvePresentationFocusTarget(payload));
}

function resolveChatFocusTarget(payload) {
    return resolvePresentationFocusTarget(payload);
}

function appendChatMessage(payload) {
    updateChatEnvelopeState(payload);

    const messages = Array.isArray(payload.messages)
        ? payload.messages
        : payload.message
        ? [payload.message]
        : [payload];

    messages.forEach(message => {
        replaceMessageById(message);
    });

    bumpChatRenderVersion();
    setViewMode('chat', resolveChatFocusTarget(payload));
}

function ensureStreamingMessage(payload) {
    const messageId = payload.message_id || payload.id;
    if (!messageId) {
        return null;
    }

    const existingMessage = appState.chat.messages.find(message => message.id === messageId);
    if (existingMessage) {
        return existingMessage;
    }

    const streamingMessage = {
        id: messageId,
        role: payload.role || 'assistant',
        content: Array.isArray(payload.content) ? payload.content : [],
        streaming: true,
        streamId: typeof payload.stream_id === 'string' ? payload.stream_id : null,
        streamSequence: -1,
    };
    replaceMessageById(streamingMessage);
    return streamingMessage;
}

function findStreamingMessage(messageId) {
    return appState.chat.messages.find(message => message.id === messageId) || null;
}

function beginChatStream(payload) {
    const messageId = payload.message_id || payload.id;
    const streamId = typeof payload.stream_id === 'string' && payload.stream_id.trim() ? payload.stream_id.trim() : null;
    if (!messageId || !streamId) {
        return;
    }

    updateChatEnvelopeState(payload);

    const existingMessage = findStreamingMessage(messageId);
    if (!existingMessage) {
        ensureStreamingMessage(payload);
    } else {
        updateSingleChatMessage(messageId, message => ({
            ...message,
            role: payload.role || message.role || 'assistant',
            content: message.streamId === streamId ? message.content : [],
            streaming: true,
            streamId,
            streamSequence: message.streamId === streamId ? message.streamSequence ?? -1 : -1,
            streamAborted: false,
        }));
    }

    setViewMode('chat');
}

function applyChatStreamDelta(payload) {
    const messageId = payload.message_id || payload.id;
    const streamId = typeof payload.stream_id === 'string' && payload.stream_id.trim() ? payload.stream_id.trim() : null;
    const delta = typeof payload.delta === 'string' ? payload.delta : '';
    if (!messageId || !streamId || !delta) {
        return;
    }

    updateChatEnvelopeState(payload);

    const incomingSequence = Number.isInteger(payload.sequence) ? payload.sequence : null;
    const existingMessage = findStreamingMessage(messageId);
    if (!existingMessage || existingMessage.streamId !== streamId || existingMessage.streaming !== true) {
        return;
    }
    updateSingleChatMessage(messageId, message => {
        const currentSequence = Number.isInteger(message.streamSequence) ? message.streamSequence : -1;
        if (incomingSequence !== null && incomingSequence <= currentSequence) {
            return message;
        }

        const contentBlocks = Array.isArray(message.content) ? [...message.content] : [];
        const textBlockIndex = contentBlocks.findIndex(block => block?.type === 'text');
        if (textBlockIndex >= 0) {
            const currentText = typeof contentBlocks[textBlockIndex]?.text === 'string' ? contentBlocks[textBlockIndex].text : '';
            contentBlocks[textBlockIndex] = { ...contentBlocks[textBlockIndex], text: `${currentText}${delta}` };
        } else {
            contentBlocks.unshift({ type: 'text', text: delta });
        }

        return {
            ...message,
            content: contentBlocks,
            streaming: true,
            streamId,
            streamSequence: incomingSequence ?? currentSequence + 1,
        };
    });

    setViewMode('chat');
}

function endChatStream(payload) {
    const messageId = payload.message_id || payload.id;
    const streamId = typeof payload.stream_id === 'string' && payload.stream_id.trim() ? payload.stream_id.trim() : null;
    const finalSequence = Number.isInteger(payload.final_sequence) ? payload.final_sequence : null;
    if (!messageId || !streamId || finalSequence === null) {
        return;
    }

    updateChatEnvelopeState(payload);

    const existingMessage = findStreamingMessage(messageId);
    if (!existingMessage) {
        replaceMessageById({
            id: messageId,
            role: 'assistant',
            content: payload.content || [],
            streaming: false,
            streamId,
            streamSequence: finalSequence,
        });
        setViewMode('chat', resolveChatFocusTarget(payload));
        return;
    }

    updateSingleChatMessage(messageId, message => {
        if (message.streamId !== streamId) {
            return message;
        }

        const currentSequence = Number.isInteger(message.streamSequence) ? message.streamSequence : -1;
        if (finalSequence < currentSequence) {
            return message;
        }

        return {
            ...message,
            content: payload.content || message.content,
            streaming: false,
            streamId,
            streamSequence: finalSequence,
            streamAborted: false,
        };
    });

    setViewMode('chat', resolveChatFocusTarget(payload));
}

function abortChatStream(payload) {
    const messageId = payload.message_id || payload.id;
    const streamId = typeof payload.stream_id === 'string' && payload.stream_id.trim() ? payload.stream_id.trim() : null;
    const lastSequence = Number.isInteger(payload.last_sequence) ? payload.last_sequence : null;
    if (!messageId || !streamId || lastSequence === null) {
        return;
    }

    updateSingleChatMessage(messageId, message => {
        if (message.streamId !== streamId) {
            return message;
        }

        const currentSequence = Number.isInteger(message.streamSequence) ? message.streamSequence : -1;
        if (lastSequence < currentSequence) {
            return message;
        }

        return {
            ...message,
            streaming: false,
            streamAborted: true,
            streamId,
            streamSequence: lastSequence,
        };
    });

    setViewMode('chat');
}

function updateChatMessage(payload) {
    const messageId = payload.message_id || payload.id;
    if (!messageId) {
        return;
    }

    updateChatEnvelopeState(payload);

    updateSingleChatMessage(messageId, message => ({
        ...message,
        content: payload.content || message.content,
    }));
    setViewMode('chat', resolveChatFocusTarget(payload));
}

function showError(payload) {
    const errorMessage = payload.error_message || t('no_content', 'No content available.');
    const details = typeof payload.details === 'string' ? payload.details.trim() : '';
    const fullMessage = details ? `${errorMessage}\n\n${details}` : errorMessage;
    const statusMessage = `${t('error_prefix', 'Error')}: ${errorMessage}`;

    if (appState.view.mode === 'chat' || appState.chat.active) {
        setControlsVisible(true);
        setStatus(statusMessage, true);
        setPendingFocus('status');
        return;
    }

    resetChatState();
    resetDisplayState();
    setControlsVisible(true);
    showDisplayText(`${t('error_prefix', 'Error')}: ${fullMessage}`, 'status');
    setCopyBuffers(fullMessage, fullMessage);
    setStatus(statusMessage, true);
}

function updateProgress(payload) {
    resetChatState();
    resetDisplayState();
    setControlsVisible(true);
    const progressMessage = payload.message || t('progress_default_message', 'Working...');
    showDisplayText(`${t('progress_prefix', 'Progress')}: ${progressMessage}`, 'content');
    setCopyBuffers(payload.message || '', payload.message || '');
    setStatus(`${t('progress_prefix', 'Progress')}: ${progressMessage}`);
}

function closeWindow() {
    setStatus(t('window_closed_message', 'Window closed by host command.'), true);
}

const COMMAND_HANDLERS = {
    render_display: payload => {
        resetChatState();
        resetDisplayState();
        renderDisplay(payload);
    },
    open_chat: (payload, commandId) => openChat(commandId, payload),
    sync_session: payload => syncSession(payload),
    chat_set_history: payload => setChatHistory(payload),
    chat_append: payload => appendChatMessage(payload),
    chat_update: payload => updateChatMessage(payload),
    chat_stream_begin: payload => beginChatStream(payload),
    chat_stream_delta: payload => applyChatStreamDelta(payload),
    chat_stream_end: payload => endChatStream(payload),
    chat_stream_abort: payload => abortChatStream(payload),
    show_error: payload => showError(payload),
    update_progress: payload => updateProgress(payload),
    close_window: () => closeWindow(),
};

export function emitUiEvent(name, commandId, details = {}) {
    window.__sendHostEvent({
        schema: 'nvda.ui_host',
        version: 2,
        id: `web-ui-${name}-${Date.now()}`,
        correlation_id: commandId,
        source: 'web_ui',
        type: 'event',
        event: {
            name,
            payload: { command_id: commandId, ...details },
        },
    });
}

export function handleHostEnvelope(envelope) {
    if (!envelope || envelope.schema !== 'nvda.ui_host') {
        setStatus(t('unknown_schema_status', 'Unknown host schema.'), true);
        reportUiFailure(envelope?.id ?? null, 'invalid_schema');
        return;
    }

    if (envelope.version !== 2) {
        setStatus(t('unsupported_protocol_status', 'Unsupported host protocol version.'), true);
        reportUiFailure(envelope.id, 'unsupported_version');
        return;
    }

    if (envelope.type !== 'command' || !envelope.command?.name) {
        setStatus(t('unknown_message_type_status', 'Unknown host message type.'), true);
        reportUiFailure(envelope.id ?? null, 'unexpected_message_type');
        return;
    }

    const commandId = envelope.correlation_id || envelope.id;
    appState.currentCommandId = commandId;
    const payload = envelope.command.payload || {};
    const hostStatusMessage = getHostStatusMessage(payload);

    mergeLocalizedStrings(payload);
    updateControlState(payload);
    setWindowTitle(payload.title || 'NVDA UI Host');

    const commandHandler = COMMAND_HANDLERS[envelope.command.name];
    if (!commandHandler) {
        resetChatState();
        resetDisplayState();
        showDisplayText(`${t('unhandled_command_prefix', 'Unhandled command')}: ${envelope.command.name}`, 'content');
        reportUiFailure(commandId, 'unknown_command');
        return;
    }

    commandHandler(payload, commandId);

    setStatus(hostStatusMessage || `${t('command_prefix', 'Command')}: ${envelope.command.name}`, Boolean(hostStatusMessage));

    reportUiApplied(commandId);
}

export function initializeWebViewBridge() {
    ensureSendHostEvent();

    if (!window.chrome?.webview?.addEventListener) {
        setStatus(t('bridge_unavailable_status', 'WebView bridge unavailable.'), true);
        return () => {};
    }

    const handleMessage = event => {
        let envelope;

        try {
            envelope = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
        } catch (error) {
            setStatus(t('parse_host_message_failed_status', 'Unable to parse host message.'), true);
            console.error('WebView host message parse error', error);
            reportUiFailure(null, 'invalid_json');
            return;
        }

        try {
            handleHostEnvelope(envelope);
        } catch (error) {
            setStatus(t('apply_host_command_failed_status', 'Unable to apply host command.'), true);
            console.error('WebView host message handling error', error, envelope);
            reportUiFailure(envelope?.correlation_id || envelope?.id || null, 'handler_error');
        }
    };

    window.chrome.webview.addEventListener('message', handleMessage);
    emitUiEvent('web_ui_ready', null);

    return () => {
        window.chrome.webview.removeEventListener?.('message', handleMessage);
    };
}
