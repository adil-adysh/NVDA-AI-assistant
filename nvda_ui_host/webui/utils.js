import { chatPanelEl, contentEl, statusEl } from './dom.js';
import { appState } from './state.js';

export function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export function setStatus(message) {
    statusEl.textContent = message;
}

export function setContentText(message) {
    contentEl.textContent = message;
}

export function setChatPanelVisible(visible) {
    if (!chatPanelEl) {
        return;
    }

    chatPanelEl.style.display = visible ? 'block' : 'none';
}

export function ensureSendHostEvent() {
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

export function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        setStatus(appState.localizedStrings.copied_status || 'Copied to clipboard.');
    }).catch(error => {
        setStatus(appState.localizedStrings.copy_failed_status || 'Copy failed.');
        console.error(error);
    });
}
