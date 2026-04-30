const contentEl = document.getElementById('content');
const statusEl = document.getElementById('status');
const chatPanelEl = document.getElementById('chat-panel');
const chatInputEl = document.getElementById('chat-input');
const chatSendEl = document.getElementById('chat-send');
let copyText = '';
let copyHtml = '';

const chatState = {
    active: false,
    commandId: null,
    conversationId: null,
    messages: [],
};

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

function setStatus(message) {
    statusEl.textContent = message;
}

function setChatPanelVisible(visible) {
    if (!chatPanelEl) {
        return;
    }

    chatPanelEl.style.display = visible ? 'block' : 'none';
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function createChatMessageHtml(message) {
    const role = message.role || 'user';
    const content = Array.isArray(message.content)
        ? message.content.map(item => item.text || '').join('')
        : String(message.content || '');

    return `
        <div class="chat-message ${escapeHtml(role)}" data-message-id="${escapeHtml(message.id || '')}">
            <div class="role">${escapeHtml(role)}</div>
            <div class="text">${escapeHtml(content)}</div>
        </div>
    `;
}

function renderChatHistory(payload) {
    chatState.active = true;
    chatState.conversationId = payload.conversation_id || null;
    chatState.commandId = payload.command_id || chatState.commandId;
    chatState.messages = Array.isArray(payload.messages) ? payload.messages : [];

    const html = chatState.messages.map(createChatMessageHtml).join('');
    contentEl.innerHTML = html || 'No chat messages available.';
    setChatPanelVisible(true);
    scrollChatToBottom();
}

function appendChatMessage(payload) {
    if (!chatState.active) {
        chatState.active = true;
        setChatPanelVisible(true);
    }

    const messages = Array.isArray(payload.messages)
        ? payload.messages
        : payload.message
        ? [payload.message]
        : [payload];

    messages.forEach(message => {
        const html = createChatMessageHtml(message);
        contentEl.insertAdjacentHTML('beforeend', html);
        if (message.id) {
            chatState.messages = chatState.messages.filter(m => m.id !== message.id);
        }
        chatState.messages.push(message);
    });

    scrollChatToBottom();
}

function updateChatMessage(payload) {
    const messageId = payload.message_id || payload.id;
    if (!messageId) {
        return;
    }

    const existing = contentEl.querySelector(`[data-message-id="${messageId}"]`);
    const text = Array.isArray(payload.content)
        ? payload.content.map(item => item.text || '').join('')
        : String(payload.content || '');

    if (existing) {
        const textEl = existing.querySelector('.text');
        if (textEl) {
            textEl.textContent = text;
        }
    }

    chatState.messages = chatState.messages.map(message =>
        message.id === messageId ? { ...message, content: payload.content || message.content } : message
    );
    scrollChatToBottom();
}

function clearChat() {
    chatState.active = false;
    chatState.commandId = null;
    chatState.conversationId = null;
    chatState.messages = [];
    contentEl.textContent = '';
    setChatPanelVisible(false);
}

function scrollChatToBottom() {
    contentEl.scrollTop = contentEl.scrollHeight;
}

function submitChatMessage() {
    if (!chatInputEl) {
        return;
    }

    const message = chatInputEl.value.trim();
    if (!message) {
        return;
    }

    reportUiEvent('chat_submitted', chatState.commandId, {
        conversation_id: chatState.conversationId,
        message,
    });
    setStatus('Message submitted.');
    chatInputEl.value = '';
}

function reportUiEvent(name, commandId, details = {}) {
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

function requestCloseHost() {
    reportUiEvent('close_host', null);
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        setStatus('Copied to clipboard.');
    }).catch(err => {
        setStatus('Copy failed.');
        console.error(err);
    });
}

function handleHostEnvelope(envelope) {
    if (!envelope || envelope.schema !== 'nvda.ui_host') {
        setStatus('Unknown host schema');
        reportUiFailure(envelope?.id ?? null, 'invalid_schema');
        return;
    }

    if (envelope.version !== 2) {
        setStatus('Unsupported host protocol version');
        reportUiFailure(envelope.id, 'unsupported_version');
        return;
    }

    if (envelope.type !== 'command' || !envelope.command?.name) {
        setStatus('Unknown host message type');
        reportUiFailure(envelope.id ?? null, 'unexpected_message_type');
        return;
    }

    const commandId = envelope.correlation_id || envelope.id;
    const payload = envelope.command.payload || {};
    setStatus(`Command: ${envelope.command.name}`);

    if (payload.title) {
        document.title = payload.title;
    }

    switch (envelope.command.name) {
        case 'render_display':
            clearChat();
            copyText = payload.copy_text || payload.output_text || '';
            copyHtml = payload.copy_html || payload.output_html || '';
            if (payload.output_html) {
                contentEl.innerHTML = payload.output_html;
            } else if (payload.output_text) {
                contentEl.textContent = payload.output_text;
            } else {
                contentEl.textContent = payload.message || 'No content available.';
            }
            break;
        case 'open_chat':
            chatState.active = true;
            chatState.commandId = commandId;
            chatState.conversationId = payload.conversation_id || null;
            chatState.messages = [];
            if (payload.initial_text) {
                renderChatHistory({
                    conversation_id: chatState.conversationId,
                    messages: [
                        {
                            id: `initial-${Date.now()}`,
                            role: 'assistant',
                            content: [{ type: 'text', text: payload.initial_text }],
                        },
                    ],
                });
            } else {
                contentEl.textContent = '';
                setChatPanelVisible(true);
            }
            copyText = payload.initial_text || '';
            copyHtml = '';
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
            clearChat();
            contentEl.textContent = `Error: ${payload.error_message || 'Unknown error'}`;
            copyText = payload.error_message || '';
            copyHtml = '';
            break;
        case 'update_progress':
            clearChat();
            contentEl.textContent = `Progress: ${payload.message || '...'}`;
            copyText = payload.message || '';
            copyHtml = '';
            break;
        case 'close_window':
            clearChat();
            contentEl.textContent = 'Window closed by host command.';
            copyText = '';
            copyHtml = '';
            break;
        default:
            clearChat();
            contentEl.textContent = `Unhandled command: ${envelope.command.name}`;
            reportUiFailure(commandId, 'unknown_command');
            return;
    }

    reportUiApplied(commandId);
}

function setupWebViewBridge() {
    ensureSendHostEvent();
    if (window.chrome?.webview?.addEventListener) {
        window.chrome.webview.addEventListener('message', event => {
            console.log('JS RECEIVED MESSAGE');
            let envelope;

            try {
                envelope = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
            } catch (err) {
                setStatus('Unable to parse host message');
                console.error('WebView host message parse error', err);
                reportUiFailure(null, 'invalid_json');
                return;
            }

            try {
                handleHostEnvelope(envelope);
            } catch (err) {
                setStatus('Unable to apply host command');
                console.error('WebView host message handling error', err, envelope);
                reportUiFailure(envelope?.correlation_id || envelope?.id || null, 'handler_error');
            }
        });
    } else {
        setStatus('WebView bridge unavailable');
    }
}

chatSendEl?.addEventListener('click', submitChatMessage);
chatInputEl?.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submitChatMessage();
    }
});

document.getElementById('copy-text').onclick = () => copyToClipboard(copyText || contentEl.textContent || '');
document.getElementById('copy-html').onclick = () => copyToClipboard(copyHtml || copyText || '');
document.getElementById('clear').onclick = () => {
    contentEl.textContent = '';
    setStatus('Content cleared.');
};
document.getElementById('close-window').onclick = () => requestCloseHost();
document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
        requestCloseHost();
    }
});

setupWebViewBridge();
