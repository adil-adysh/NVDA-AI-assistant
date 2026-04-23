const contentEl = document.getElementById('content');
const statusEl = document.getElementById('status');
let copyText = '';
let copyHtml = '';

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
            copyText = payload.initial_text || '';
            copyHtml = '';
            contentEl.textContent = `${payload.title || 'Chat'}\n\n${payload.initial_text || ''}`;
            break;
        case 'show_error':
            contentEl.textContent = `Error: ${payload.error_message || 'Unknown error'}`;
            copyText = payload.error_message || '';
            copyHtml = '';
            break;
        case 'update_progress':
            contentEl.textContent = `Progress: ${payload.message || '...'}`;
            copyText = payload.message || '';
            copyHtml = '';
            break;
        case 'close_window':
            contentEl.textContent = 'Window closed by host command.';
            copyText = '';
            copyHtml = '';
            break;
        default:
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
            try {
                const envelope = JSON.parse(event.data);
                handleHostEnvelope(envelope);
            } catch (err) {
                setStatus('Unable to parse host message');
                console.error('WebView host message parse error', err);
                reportUiFailure(null, 'invalid_json');
            }
        });
    } else {
        setStatus('WebView bridge unavailable');
    }
}

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
