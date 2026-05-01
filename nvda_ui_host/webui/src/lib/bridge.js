import { addInitialImageAttachment } from './attachments.js';
import {
    appState,
    mergeLocalizedStrings,
    resetChatState,
    resetDisplayState,
    setCopyBuffers,
    setDisplayBlocks,
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

function updateControlState(payload) {
    const metadata = payload?.metadata || {};
    const providerState = payload?.provider_state || metadata.provider_state || {};
    const availableProviders = payload?.available_providers || metadata.available_providers || [];
    const availableModels = payload?.available_models || metadata.available_models || [];
    const thinkEnabled = payload?.think_enabled ?? metadata.think_enabled ?? false;

    appState.control.availableProviders = Array.isArray(availableProviders) ? availableProviders : [];
    appState.control.availableModels = Array.isArray(availableModels) ? availableModels : [];
    appState.control.selectedProvider = String(providerState.provider || appState.control.selectedProvider || '');
    appState.control.selectedModel = String(providerState.model || appState.control.selectedModel || '');
    appState.control.thinkEnabled = Boolean(thinkEnabled);
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

    if (payload.initial_text) {
        appState.chat.messages = [
            {
                id: `initial-${Date.now()}`,
                role: 'assistant',
                content: [{ type: 'text', text: payload.initial_text }],
            },
        ];
    }

    setCopyBuffers(payload.initial_text || '', payload.initial_text || '');
    setViewMode('chat', 'composer');
}

function syncSession(payload) {
    if (payload.conversation_id) {
        appState.chat.conversationId = payload.conversation_id;
    }
}

function renderDisplay(payload) {
    const metadata = payload?.metadata || {};
    const actions = payload?.actions || metadata.actions || [];
    const thinkingTrace = payload?.thinking_trace || metadata.thinking_trace || null;
    const thinkingSummary = payload?.thinking_summary || metadata.thinking_summary || null;
    const thinkingCollapsed = payload?.thinking_visible_by_default === false || metadata.thinking_visible_by_default === false;
    const blocks = [];

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

    setDisplayBlocks(blocks, Array.isArray(actions) ? actions : []);
    setViewMode('display');
    setPendingFocus((payload?.actions || payload?.metadata?.actions || []).length ? 'first-result-action' : 'content');
    setCopyBuffers(payload.copy_text || payload.output_text || '', payload.copy_markdown || '');
}

function setChatHistory(payload) {
    appState.chat.active = true;
    appState.chat.conversationId = payload.conversation_id || null;
    appState.chat.commandId = payload.command_id || appState.chat.commandId;
    appState.chat.messages = Array.isArray(payload.messages) ? payload.messages : [];
    setViewMode('chat', 'composer');
}

function appendChatMessage(payload) {
    appState.chat.active = true;

    if (payload.conversation_id) {
        appState.chat.conversationId = payload.conversation_id;
    }

    if (payload.command_id) {
        appState.chat.commandId = payload.command_id;
    }

    const messages = Array.isArray(payload.messages)
        ? payload.messages
        : payload.message
        ? [payload.message]
        : [payload];

    messages.forEach(message => {
        if (message.id) {
            appState.chat.messages = appState.chat.messages.filter(candidate => candidate.id !== message.id);
        }

        appState.chat.messages.push(message);
    });

    setViewMode('chat', 'composer');
}

function updateChatMessage(payload) {
    const messageId = payload.message_id || payload.id;
    if (!messageId) {
        return;
    }

    if (payload.conversation_id) {
        appState.chat.conversationId = payload.conversation_id;
    }

    if (payload.command_id) {
        appState.chat.commandId = payload.command_id;
    }

    appState.chat.messages = appState.chat.messages.map(message =>
        message.id === messageId ? { ...message, content: payload.content || message.content } : message
    );

    setViewMode('chat', 'composer');
}

function showError(payload) {
    resetChatState();
    resetDisplayState();
    const errorMessage = payload.error_message || t('no_content', 'No content available.');
    const details = typeof payload.details === 'string' ? payload.details.trim() : '';
    const fullMessage = details ? `${errorMessage}\n\n${details}` : errorMessage;
    showDisplayText(`${t('error_prefix', 'Error')}: ${fullMessage}`, 'status');
    setCopyBuffers(fullMessage, fullMessage);
    setStatus(`${t('error_prefix', 'Error')}: ${errorMessage}`, true);
}

function updateProgress(payload) {
    resetChatState();
    resetDisplayState();
    const progressMessage = payload.message || t('progress_default_message', 'Working...');
    showDisplayText(`${t('progress_prefix', 'Progress')}: ${progressMessage}`, 'content');
    setCopyBuffers(payload.message || '', payload.message || '');
    setStatus(`${t('progress_prefix', 'Progress')}: ${progressMessage}`);
}

function closeWindow() {
    resetChatState();
    resetDisplayState();
    const message = t('window_closed_message', 'Window closed by host command.');
    showDisplayText(message, 'status');
    setCopyBuffers('', '');
    setStatus(message, true);
}

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

    mergeLocalizedStrings(payload);
    updateControlState(payload);
    setStatus(`${t('command_prefix', 'Command')}: ${envelope.command.name}`);
    setWindowTitle(payload.title || 'NVDA UI Host');

    switch (envelope.command.name) {
        case 'render_display':
            resetChatState();
            resetDisplayState();
            renderDisplay(payload);
            break;
        case 'open_chat':
            openChat(commandId, payload);
            break;
        case 'sync_session':
            syncSession(payload);
            break;
        case 'chat_set_history':
            setChatHistory(payload);
            break;
        case 'chat_append':
            appendChatMessage(payload);
            break;
        case 'chat_update':
            updateChatMessage(payload);
            break;
        case 'show_error':
            showError(payload);
            break;
        case 'update_progress':
            updateProgress(payload);
            break;
        case 'close_window':
            closeWindow();
            break;
        default:
            resetChatState();
            resetDisplayState();
            showDisplayText(`${t('unhandled_command_prefix', 'Unhandled command')}: ${envelope.command.name}`, 'content');
            reportUiFailure(commandId, 'unknown_command');
            return;
    }

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

    return () => {
        window.chrome.webview.removeEventListener?.('message', handleMessage);
    };
}
