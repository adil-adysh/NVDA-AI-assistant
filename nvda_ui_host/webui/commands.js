import {
    chatInputEl,
    modelInputEl,
    modelOptionsEl,
    providerSelectEl,
    thinkToggleEl,
} from './dom.js';
import { t, applyLocalizedStrings } from './localization.js';
import { appState } from './state.js';
import { ensureSendHostEvent, setStatus } from './utils.js';
import {
    appendChatMessage,
    clearChat,
    renderChatHistory,
    renderChatState,
    renderDisplayPayload,
    renderDisplayState,
    resetChatState,
    resetDisplayState,
    setDisplayText,
    showInitialChatImage,
    updateChatMessage,
} from './rendering.js';
import { clearPendingAttachments } from './attachments.js';

function renderControlState(payload) {
    const metadata = payload?.metadata || {};
    const providerState = payload?.provider_state || metadata.provider_state || {};
    const availableProviders = payload?.available_providers || metadata.available_providers || [];
    const availableModels = payload?.available_models || metadata.available_models || [];
    const thinkEnabled = payload?.think_enabled ?? metadata.think_enabled ?? false;

    appState.controlState.availableProviders = Array.isArray(availableProviders) ? availableProviders : [];
    appState.controlState.availableModels = Array.isArray(availableModels) ? availableModels : [];
    appState.controlState.selectedProvider = String(providerState.provider || appState.controlState.selectedProvider || '');
    appState.controlState.selectedModel = String(providerState.model || appState.controlState.selectedModel || '');
    appState.controlState.thinkEnabled = Boolean(thinkEnabled);

    providerSelectEl.innerHTML = appState.controlState.availableProviders.map(provider => {
        if (typeof provider === 'string') {
            return `<option value="${provider}">${provider}</option>`;
        }
        const id = provider.id || provider.value || '';
        const label = provider.label || id;
        return `<option value="${id}">${label}</option>`;
    }).join('');

    if (appState.controlState.selectedProvider) {
        providerSelectEl.value = appState.controlState.selectedProvider;
    }

    modelOptionsEl.innerHTML = appState.controlState.availableModels
        .map(model => `<option value="${String(model)}"></option>`)
        .join('');
    modelInputEl.value = appState.controlState.selectedModel;
    thinkToggleEl.checked = appState.controlState.thinkEnabled;
}

export function reportUiEvent(name, commandId, details = {}) {
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

function reportUiApplied(commandId) {
    reportUiEvent('ui_applied', commandId);
}

function reportUiFailure(commandId, reason) {
    reportUiEvent('ui_failed', commandId, { reason });
}

export function requestCloseHost() {
    reportUiEvent('close_host', null);
}

export function submitChatMessage() {
    if (!chatInputEl) {
        return;
    }

    const message = chatInputEl.value.trim();
    const attachments = Array.isArray(appState.chatState.attachments) ? appState.chatState.attachments : [];
    if (!message && attachments.length === 0) {
        return;
    }

    reportUiEvent('chat_submitted', appState.chatState.commandId, {
        conversation_id: appState.chatState.conversationId,
        message,
        attachments,
    });
    setStatus(t('submitted_status', 'Message submitted.'));
    chatInputEl.value = '';
    clearPendingAttachments();
}

export function submitProviderSelection() {
    const provider = providerSelectEl.value.trim();
    if (!provider) {
        return;
    }
    appState.controlState.selectedProvider = provider;
    reportUiEvent('provider_selected', appState.currentCommandId, { provider });
}

export function submitModelSelection() {
    const model = modelInputEl.value.trim();
    if (!model) {
        return;
    }
    appState.controlState.selectedModel = model;
    reportUiEvent('model_selected', appState.currentCommandId, {
        provider: providerSelectEl.value.trim() || null,
        model,
    });
}

export function submitThinkModeToggle() {
    appState.controlState.thinkEnabled = thinkToggleEl.checked;
    reportUiEvent('think_mode_toggled', appState.currentCommandId, { enabled: thinkToggleEl.checked });
}

export function handleResultActionClick(target) {
    const actionId = target?.dataset?.actionId;
    if (!actionId) {
        return;
    }

    let payload = {};
    const rawPayload = target.dataset.actionPayload || '{}';
    try {
        payload = JSON.parse(rawPayload);
    } catch (error) {
        console.error('Unable to parse action payload', error);
    }

    reportUiEvent('ui_action_invoked', appState.currentCommandId, { action_id: actionId, payload });
}

function handleOpenChatCommand(commandId, payload) {
    resetChatState();
    resetDisplayState();
    appState.chatState.active = true;
    appState.chatState.commandId = commandId;
    appState.chatState.conversationId = payload.conversation_id || null;
    showInitialChatImage(payload.initial_image_base64);
    if (payload.initial_text) {
        renderChatHistory({
            conversation_id: appState.chatState.conversationId,
            messages: [
                {
                    id: `initial-${Date.now()}`,
                    role: 'assistant',
                    content: [{ type: 'text', text: payload.initial_text }],
                },
            ],
        });
    } else {
        renderChatState();
    }
    appState.copyText = payload.initial_text || '';
    appState.copyMarkdown = payload.initial_text || '';
}

function handleSyncSessionCommand(payload) {
    if (payload.conversation_id) {
        appState.chatState.conversationId = payload.conversation_id;
    }

    if (appState.chatState.active) {
        renderChatState();
        return;
    }

    if (appState.displayState.blocks.length > 0 || appState.displayState.actions.length > 0) {
        renderDisplayState();
    }
}

function handleErrorCommand(payload) {
    clearChat();
    const errorMessage = payload.error_message || t('no_content', 'No content available.');
    const details = typeof payload.details === 'string' ? payload.details.trim() : '';
    const fullMessage = details ? `${errorMessage}\n\n${details}` : errorMessage;
    setDisplayText(`${t('error_prefix', 'Error')}: ${fullMessage}`);
    appState.copyText = fullMessage;
    appState.copyMarkdown = fullMessage;
}

function handleProgressCommand(payload) {
    clearChat();
    setDisplayText(`${t('progress_prefix', 'Progress')}: ${payload.message || t('progress_default_message', 'Working...')}`);
    appState.copyText = payload.message || '';
    appState.copyMarkdown = payload.message || '';
}

function handleCloseWindowCommand() {
    clearChat();
    setDisplayText(t('window_closed_message', 'Window closed by host command.'));
    appState.copyText = '';
    appState.copyMarkdown = '';
}

export function handleHostEnvelope(envelope) {
    if (!envelope || envelope.schema !== 'nvda.ui_host') {
        setStatus(t('unknown_schema_status', 'Unknown host schema.'));
        reportUiFailure(envelope?.id ?? null, 'invalid_schema');
        return;
    }

    if (envelope.version !== 2) {
        setStatus(t('unsupported_protocol_status', 'Unsupported host protocol version.'));
        reportUiFailure(envelope.id, 'unsupported_version');
        return;
    }

    if (envelope.type !== 'command' || !envelope.command?.name) {
        setStatus(t('unknown_message_type_status', 'Unknown host message type.'));
        reportUiFailure(envelope.id ?? null, 'unexpected_message_type');
        return;
    }

    const commandId = envelope.correlation_id || envelope.id;
    appState.currentCommandId = commandId;
    const payload = envelope.command.payload || {};
    applyLocalizedStrings(payload);
    renderControlState(payload);
    setStatus(`${t('command_prefix', 'Command')}: ${envelope.command.name}`);

    if (payload.title) {
        document.title = payload.title;
    }

    switch (envelope.command.name) {
        case 'render_display':
            resetChatState();
            resetDisplayState();
            appState.copyText = payload.copy_text || payload.output_text || '';
            appState.copyMarkdown = payload.copy_markdown || payload.output_text || '';
            renderDisplayPayload(payload);
            break;
        case 'open_chat':
            handleOpenChatCommand(commandId, payload);
            break;
        case 'sync_session':
            handleSyncSessionCommand(payload);
            break;
        case 'chat_set_history':
            renderChatHistory(payload);
            break;
        case 'chat_append':
            appendChatMessage(payload);
            break;
        case 'chat_update':
            updateChatMessage(payload);
            break;
        case 'show_error':
            handleErrorCommand(payload);
            break;
        case 'update_progress':
            handleProgressCommand(payload);
            break;
        case 'close_window':
            handleCloseWindowCommand();
            break;
        default:
            clearChat();
            setDisplayText(`${t('unhandled_command_prefix', 'Unhandled command')}: ${envelope.command.name}`);
            reportUiFailure(commandId, 'unknown_command');
            return;
    }

    reportUiApplied(commandId);
}

export function setupWebViewBridge() {
    ensureSendHostEvent();
    if (window.chrome?.webview?.addEventListener) {
        window.chrome.webview.addEventListener('message', event => {
            let envelope;

            try {
                envelope = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
            } catch (error) {
                setStatus(t('parse_host_message_failed_status', 'Unable to parse host message.'));
                console.error('WebView host message parse error', error);
                reportUiFailure(null, 'invalid_json');
                return;
            }

            try {
                handleHostEnvelope(envelope);
            } catch (error) {
                setStatus(t('apply_host_command_failed_status', 'Unable to apply host command.'));
                console.error('WebView host message handling error', error, envelope);
                reportUiFailure(envelope?.correlation_id || envelope?.id || null, 'handler_error');
            }
        });
    } else {
        setStatus(t('bridge_unavailable_status', 'WebView bridge unavailable.'));
    }
}
