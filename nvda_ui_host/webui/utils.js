import { chatInputEl, chatPanelEl, contentEl, statusEl } from './dom.js';
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

export function isTextEntryTarget(target) {
    return target instanceof HTMLInputElement
        || target instanceof HTMLTextAreaElement
        || target instanceof HTMLSelectElement
        || target?.isContentEditable === true;
}

export function queueFocus(target) {
    appState.viewState.pendingFocus = target;
}

function focusElement(element) {
    if (!(element instanceof HTMLElement)) {
        return;
    }
    window.requestAnimationFrame(() => {
        element.focus({ preventScroll: false });
    });
}

export function focusPendingTarget() {
    const target = appState.viewState.pendingFocus;
    appState.viewState.pendingFocus = null;

    if (target === 'status') {
        focusElement(statusEl);
        return;
    }

    if (target === 'composer') {
        if (chatPanelEl?.style.display !== 'none' && chatInputEl instanceof HTMLElement) {
            focusElement(chatInputEl);
            return;
        }
    }

    if (target === 'first-result-action') {
        const actionButton = contentEl.querySelector('[data-action-id]');
        if (actionButton instanceof HTMLElement) {
            focusElement(actionButton);
            return;
        }
    }

    if (target === 'content') {
        focusElement(contentEl);
    }
}

export function focusContentRegion() {
    queueFocus('content');
    focusPendingTarget();
}

export function focusChatComposer() {
    queueFocus('composer');
    focusPendingTarget();
}
