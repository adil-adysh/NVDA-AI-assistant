import { contentEl } from './dom.js';
import { clearPendingAttachments, renderAttachments, upsertAttachment } from './attachments.js';
import { t } from './localization.js';
import { appState } from './state.js';
import { copyToClipboard, escapeHtml, setChatPanelVisible, setStatus } from './utils.js';

export function normalizeContentBlocks(content) {
    if (Array.isArray(content)) {
        return content;
    }
    if (content === null || content === undefined || content === '') {
        return [];
    }
    return [{ type: 'text', text: String(content) }];
}

function createThinkingHtml(trace, summary, collapsed = true) {
    if (!trace) {
        return '';
    }

    const summaryText = summary || t('thinking_label', 'Thinking');
    return `
        <details class="thinking-block" ${collapsed ? '' : 'open'}>
            <summary>${escapeHtml(summaryText)}</summary>
            <div class="text">${escapeHtml(trace)}</div>
        </details>
    `;
}

function createContentBlockHtml(block) {
    if (!block || typeof block !== 'object') {
        return '';
    }

    if (block.type === 'thinking') {
        return createThinkingHtml(
            block.text || '',
            block.summary || t('thinking_trace_label', 'Thinking trace'),
            block.collapsed !== false,
        );
    }

    if (block.type === 'html') {
        return `<div class="content-block html">${block.html || ''}</div>`;
    }

    return `<div class="content-block text">${escapeHtml(block.text || '')}</div>`;
}

export function renderBlocksHtml(blocks) {
    return normalizeContentBlocks(blocks)
        .map(createContentBlockHtml)
        .join('');
}

function extractTextFromHtml(html) {
    if (!html) {
        return '';
    }

    const container = document.createElement('div');
    container.innerHTML = html;
    return (container.textContent || '').trim();
}

export function extractTextFromBlocks(blocks) {
    return normalizeContentBlocks(blocks)
        .map(block => {
            if (!block || typeof block !== 'object') {
                return '';
            }
            if (block.type === 'thinking') {
                return `${block.summary || t('thinking_trace_label', 'Thinking trace')}\n${block.text || ''}`.trim();
            }
            if (block.type === 'html') {
                return extractTextFromHtml(block.html || '');
            }
            return String(block.text || '').trim();
        })
        .filter(Boolean)
        .join('\n\n');
}

export function extractMarkdownFromBlocks(blocks) {
    return normalizeContentBlocks(blocks)
        .map(block => {
            if (!block || typeof block !== 'object') {
                return '';
            }
            if (block.type === 'thinking') {
                const summary = block.summary || t('thinking_trace_label', 'Thinking trace');
                const text = String(block.text || '').trim();
                return text ? `### ${summary}\n\n${text}` : '';
            }
            if (block.type === 'html') {
                return extractTextFromHtml(block.html || '');
            }
            return String(block.text || '').trim();
        })
        .filter(Boolean)
        .join('\n\n');
}

export function getCurrentPlainText() {
    if (appState.chatState.active) {
        return appState.chatState.messages
            .map(message => {
                const role = String(message.role || 'assistant');
                const text = extractTextFromBlocks(message.content);
                return text ? `${role}: ${text}` : '';
            })
            .filter(Boolean)
            .join('\n\n');
    }

    return extractTextFromBlocks(appState.displayState.blocks);
}

export function getCurrentCopyText() {
    if (appState.viewState.mode === 'chat') {
        return getCurrentPlainText();
    }

    return appState.copyText || getCurrentPlainText() || contentEl.textContent || '';
}

export function getCurrentCopyMarkdown() {
    if (appState.viewState.mode === 'chat') {
        return '';
    }

    return appState.copyMarkdown || appState.copyText || getCurrentPlainText() || contentEl.textContent || '';
}

function createActionsHtml(actions) {
    if (!Array.isArray(actions) || actions.length === 0) {
        return '';
    }

    return `
        <div class="result-actions">
            ${actions.map(action => {
                const actionId = escapeHtml(action.id || '');
                const label = escapeHtml(action.label || action.id || t('result_action_fallback_label', 'Action'));
                const payload = escapeHtml(JSON.stringify(action.payload || {}));
                return `<button type="button" data-action-id="${actionId}" data-action-payload="${payload}">${label}</button>`;
            }).join('')}
        </div>
    `;
}

export function renderDisplayPayload(payload) {
    const metadata = payload?.metadata || {};
    const actions = payload?.actions || metadata.actions || [];
    const thinkingTrace = payload?.thinking_trace || metadata.thinking_trace || null;
    const thinkingSummary = payload?.thinking_summary || metadata.thinking_summary || null;
    const thinkingCollapsed = payload?.thinking_visible_by_default === false || metadata.thinking_visible_by_default === false;

    const blocks = [];
    if (payload.output_html) {
        blocks.push({ type: 'html', html: payload.output_html });
    } else {
        const text = payload.output_text || payload.message || t('no_content', 'No content available.');
        blocks.push({ type: 'text', text });
    }

    if (thinkingTrace) {
        blocks.push({
            type: 'thinking',
            text: thinkingTrace,
            summary: thinkingSummary || t('thinking_label', 'Thinking'),
            collapsed: thinkingCollapsed,
        });
    }

    appState.displayState.blocks = blocks;
    appState.displayState.actions = Array.isArray(actions) ? actions : [];
    renderDisplayState();
}

function getMessageById(messageId) {
    return appState.chatState.messages.find(message => message?.id === messageId) || null;
}

function messageHasRenderedTables(message) {
    return normalizeContentBlocks(message?.content).some(block => block?.type === 'html' && /<table[\s>]/i.test(block.html || ''));
}

function createChatMessageActionsHtml(message) {
    if (!message || message.role !== 'assistant') {
        return '';
    }

    const messageId = escapeHtml(message.id || '');
    const actions = [
        `<button type="button" data-copy-message-text="${messageId}">${escapeHtml(t('copy_response_button', 'Copy response'))}</button>`,
        `<button type="button" data-copy-message-markdown="${messageId}">${escapeHtml(t('copy_response_markdown_button', 'Copy response markdown'))}</button>`,
    ];

    if (messageHasRenderedTables(message)) {
        actions.push(`<button type="button" data-copy-message-table="${messageId}">${escapeHtml(t('copy_table_button', 'Copy table'))}</button>`);
    }

    return `<div class="chat-message-actions">${actions.join('')}</div>`;
}

function createChatMessageHtml(message) {
    const role = message.role || 'user';
    const actions = createChatMessageActionsHtml(message);

    return `
        <div class="chat-message ${escapeHtml(role)}" data-message-id="${escapeHtml(message.id || '')}">
            <div class="chat-message-header">
                <div class="role">${escapeHtml(role)}</div>
                ${actions}
            </div>
            <div class="text">${renderBlocksHtml(message.content)}</div>
        </div>
    `;
}

function escapeMarkdownCell(text) {
    return String(text || '').replace(/\|/g, '\\|').replace(/\r?\n/g, '<br>');
}

function tableElementToMarkdown(tableElement) {
    const rows = Array.from(tableElement.querySelectorAll('tr'));
    if (rows.length === 0) {
        return '';
    }

    const matrix = rows
        .map(row => Array.from(row.querySelectorAll('th, td')).map(cell => escapeMarkdownCell(cell.textContent || '')))
        .filter(cells => cells.length > 0);

    if (matrix.length === 0) {
        return '';
    }

    const columnCount = Math.max(...matrix.map(cells => cells.length));
    const normalized = matrix.map(cells => {
        const next = [...cells];
        while (next.length < columnCount) {
            next.push('');
        }
        return next;
    });

    const header = normalized[0];
    const separator = header.map(() => '---');
    const body = normalized.slice(1);

    return [header, separator, ...body]
        .map(cells => `| ${cells.join(' | ')} |`)
        .join('\n');
}

export function copyMessageText(messageId) {
    const message = getMessageById(messageId);
    if (!message) {
        return;
    }
    copyToClipboard(extractTextFromBlocks(message.content));
}

export function copyMessageMarkdown(messageId) {
    const message = getMessageById(messageId);
    if (!message) {
        return;
    }
    copyToClipboard(extractMarkdownFromBlocks(message.content));
}

export function copyMessageTable(messageId) {
    const messageEl = Array.from(contentEl.querySelectorAll('.chat-message'))
        .find(element => element instanceof HTMLElement && element.dataset.messageId === messageId);
    const tableEl = messageEl?.querySelector('table');
    if (!(tableEl instanceof HTMLTableElement)) {
        setStatus(t('copy_failed_status', 'Copy failed.'));
        return;
    }
    copyToClipboard(tableElementToMarkdown(tableEl));
}

export function renderDisplayState() {
    appState.viewState.mode = 'display';
    renderCurrentView();
}

export function setDisplayText(text) {
    appState.displayState.blocks = text ? [{ type: 'text', text }] : [];
    appState.displayState.actions = [];
    renderDisplayState();
}

export function renderChatState() {
    appState.viewState.mode = 'chat';
    renderCurrentView();
    scrollChatToBottom();
}

export function renderCurrentView() {
    if (appState.viewState.mode === 'chat') {
        const html = appState.chatState.messages.map(createChatMessageHtml).join('');
        contentEl.innerHTML = html || t('no_chat_messages', 'No chat messages available.');
        setChatPanelVisible(true);
        renderAttachments();
        return;
    }

    contentEl.innerHTML = `${renderBlocksHtml(appState.displayState.blocks)}${createActionsHtml(appState.displayState.actions)}`;
    setChatPanelVisible(false);
    renderAttachments();
}

export function renderChatHistory(payload) {
    appState.chatState.active = true;
    appState.chatState.conversationId = payload.conversation_id || null;
    appState.chatState.commandId = payload.command_id || appState.chatState.commandId;
    appState.chatState.messages = Array.isArray(payload.messages) ? payload.messages : [];
    renderChatState();
}

export function appendChatMessage(payload) {
    if (!appState.chatState.active) {
        appState.chatState.active = true;
    }

    if (payload.conversation_id) {
        appState.chatState.conversationId = payload.conversation_id;
    }
    if (payload.command_id) {
        appState.chatState.commandId = payload.command_id;
    }

    const messages = Array.isArray(payload.messages)
        ? payload.messages
        : payload.message
        ? [payload.message]
        : [payload];

    messages.forEach(message => {
        if (message.id) {
            appState.chatState.messages = appState.chatState.messages.filter(candidate => candidate.id !== message.id);
        }
        appState.chatState.messages.push(message);
    });

    renderChatState();
}

export function updateChatMessage(payload) {
    const messageId = payload.message_id || payload.id;
    if (!messageId) {
        return;
    }

    if (payload.conversation_id) {
        appState.chatState.conversationId = payload.conversation_id;
    }
    if (payload.command_id) {
        appState.chatState.commandId = payload.command_id;
    }

    appState.chatState.messages = appState.chatState.messages.map(message =>
        message.id === messageId ? { ...message, content: payload.content || message.content } : message
    );
    renderChatState();
}

export function resetChatState() {
    appState.chatState.active = false;
    appState.chatState.commandId = null;
    appState.chatState.conversationId = null;
    appState.chatState.messages = [];
    clearPendingAttachments();
}

export function resetDisplayState() {
    appState.displayState.blocks = [];
    appState.displayState.actions = [];
}

export function clearChat() {
    resetChatState();
    resetDisplayState();
    renderDisplayState();
}

export function scrollChatToBottom() {
    contentEl.scrollTop = contentEl.scrollHeight;
}

export function showInitialChatImage(base64) {
    if (!base64) {
        return;
    }

    upsertAttachment({
        id: `initial-image-${Date.now()}`,
        kind: 'image',
        name: t('initial_image_name', 'Initial image'),
        mime_type: 'image/png',
        image_base64: base64,
    });
}
