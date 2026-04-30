const contentEl = document.getElementById('content');
const statusEl = document.getElementById('status');
const chatPanelEl = document.getElementById('chat-panel');
const chatInputEl = document.getElementById('chat-input');
const chatSendEl = document.getElementById('chat-send');
const attachFilesEl = document.getElementById('attach-files');
const fileInputEl = document.getElementById('file-input');
const attachmentStripEl = document.getElementById('attachment-strip');
const providerSelectEl = document.getElementById('provider-select');
const modelInputEl = document.getElementById('model-input');
const modelOptionsEl = document.getElementById('model-options');
const thinkToggleEl = document.getElementById('think-toggle');
const providerLabelEl = document.getElementById('provider-label');
const modelLabelEl = document.getElementById('model-label');
const thinkModeLabelEl = document.getElementById('think-mode-label');
let copyText = '';
let copyMarkdown = '';
let currentCommandId = null;

const controlState = {
    availableProviders: [],
    availableModels: [],
    selectedProvider: '',
    selectedModel: '',
    thinkEnabled: false,
};

const localizedStrings = {
    provider_label: 'Provider',
    model_label: 'Model',
    think_mode_label: 'Think mode',
    attach_button: 'Attach',
    send_button: 'Send',
    copy_text_button: 'Copy text',
    copy_markdown_button: 'Copy markdown',
    copy_response_button: 'Copy response',
    copy_response_markdown_button: 'Copy response markdown',
    copy_table_button: 'Copy table',
    clear_button: 'Clear',
    close_button: 'Close',
    chat_placeholder: 'Type your message...',
    waiting_status: 'Waiting for host command...',
    no_content: 'No content available.',
    thinking_label: 'Thinking',
    thinking_trace_label: 'Thinking trace',
    remove_attachment: 'Remove',
    attachment_fallback_name: 'Attachment',
    initial_image_name: 'Initial image',
    image_attachment_notice: '[Image attachment included]',
    submitted_status: 'Message submitted.',
    attach_failed_status: 'Unable to attach file.',
    content_cleared_status: 'Content cleared.',
    copied_status: 'Copied to clipboard.',
    copy_failed_status: 'Copy failed.',
    unknown_schema_status: 'Unknown host schema.',
    unsupported_protocol_status: 'Unsupported host protocol version.',
    unknown_message_type_status: 'Unknown host message type.',
    parse_host_message_failed_status: 'Unable to parse host message.',
    apply_host_command_failed_status: 'Unable to apply host command.',
    bridge_unavailable_status: 'WebView bridge unavailable.',
    window_closed_message: 'Window closed by host command.',
    error_prefix: 'Error',
    progress_prefix: 'Progress',
    progress_default_message: 'Working...',
    command_prefix: 'Command',
    unhandled_command_prefix: 'Unhandled command',
    result_action_fallback_label: 'Action',
};

function t(key, fallback = '') {
    return localizedStrings[key] || fallback;
}

function applyLocalizedStrings(payload) {
    const metadata = payload?.metadata || {};
    const nextStrings = payload?.localized_strings || metadata.localized_strings || {};
    if (nextStrings && typeof nextStrings === 'object') {
        Object.assign(localizedStrings, nextStrings);
    }

    if (providerLabelEl) {
        providerLabelEl.textContent = t('provider_label', 'Provider');
    }
    if (modelLabelEl) {
        modelLabelEl.textContent = t('model_label', 'Model');
    }
    if (thinkModeLabelEl) {
        thinkModeLabelEl.textContent = t('think_mode_label', 'Think mode');
    }
    if (attachFilesEl) {
        attachFilesEl.textContent = t('attach_button', 'Attach');
    }
    if (chatSendEl) {
        chatSendEl.textContent = t('send_button', 'Send');
    }
    if (chatInputEl) {
        chatInputEl.placeholder = t('chat_placeholder', 'Type your message...');
    }
    const copyTextButton = document.getElementById('copy-text');
    const copyMarkdownButton = document.getElementById('copy-markdown');
    const clearButton = document.getElementById('clear');
    const closeButton = document.getElementById('close-window');
    if (copyTextButton) {
        copyTextButton.textContent = t('copy_text_button', 'Copy text');
    }
    if (copyMarkdownButton) {
        copyMarkdownButton.textContent = t('copy_markdown_button', 'Copy markdown');
    }
    if (clearButton) {
        clearButton.textContent = t('clear_button', 'Clear');
    }
    if (closeButton) {
        closeButton.textContent = t('close_button', 'Close');
    }
}

const chatState = {
    active: false,
    commandId: null,
    conversationId: null,
    messages: [],
    attachments: [],
};

const displayState = {
    blocks: [],
    actions: [],
};

const viewState = {
    mode: 'display',
};

const TEXT_FILE_EXTENSIONS = new Set([
    'txt', 'md', 'markdown', 'json', 'yaml', 'yml', 'csv', 'tsv', 'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'htm', 'xml', 'css', 'scss', 'less', 'java', 'c', 'cpp', 'h', 'hpp', 'rs', 'go', 'rb', 'php', 'sql', 'log'
]);

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

function setContentText(message) {
    contentEl.textContent = message;
}

function setChatPanelVisible(visible) {
    if (!chatPanelEl) {
        return;
    }

    chatPanelEl.style.display = visible ? 'block' : 'none';
}

function renderAttachments() {
    if (!attachmentStripEl) {
        return;
    }

    if (viewState.mode !== 'chat') {
        attachmentStripEl.innerHTML = '';
        return;
    }

    if (!Array.isArray(chatState.attachments) || chatState.attachments.length === 0) {
        attachmentStripEl.innerHTML = '';
        return;
    }

    attachmentStripEl.innerHTML = chatState.attachments.map(attachment => `
        <div class="attachment-chip" data-attachment-id="${escapeHtml(attachment.id || '')}">
            <span>${escapeHtml(attachment.name || attachment.kind || t('attachment_fallback_name', 'Attachment'))}</span>
            <button type="button" data-remove-attachment="${escapeHtml(attachment.id || '')}">${escapeHtml(t('remove_attachment', 'Remove'))}</button>
        </div>
    `).join('');
}

function clearPendingAttachments() {
    chatState.attachments = [];
    renderAttachments();
    if (fileInputEl) {
        fileInputEl.value = '';
    }
}

function upsertAttachment(attachment) {
    chatState.attachments = chatState.attachments.filter(item => item.id !== attachment.id);
    chatState.attachments.push(attachment);
    renderAttachments();
}

function removeAttachment(attachmentId) {
    chatState.attachments = chatState.attachments.filter(item => item.id !== attachmentId);
    renderAttachments();
}

function createAttachmentId(file) {
    return `attachment-${Date.now()}-${Math.random().toString(36).slice(2, 8)}-${file.name}`;
}

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(reader.error || new Error('Unable to read file as data URL'));
        reader.readAsDataURL(file);
    });
}

function readFileAsText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(reader.error || new Error('Unable to read file as text'));
        reader.readAsText(file);
    });
}

function isTextFile(file) {
    if (file.type && file.type.startsWith('text/')) {
        return true;
    }
    const parts = file.name.toLowerCase().split('.');
    const extension = parts.length > 1 ? parts.pop() : '';
    return TEXT_FILE_EXTENSIONS.has(extension || '');
}

async function loadAttachment(file) {
    const attachmentId = createAttachmentId(file);
    if (file.type.startsWith('image/')) {
        const dataUrl = await readFileAsDataUrl(file);
        const base64 = dataUrl.includes(',') ? dataUrl.split(',', 2)[1] : dataUrl;
        return {
            id: attachmentId,
            kind: 'image',
            name: file.name,
            mime_type: file.type || 'image/png',
            image_base64: base64,
        };
    }

    if (isTextFile(file)) {
        const text = await readFileAsText(file);
        return {
            id: attachmentId,
            kind: 'file',
            name: file.name,
            mime_type: file.type || 'text/plain',
            text,
        };
    }

    throw new Error(`Unsupported file type for ${file.name}`);
}

async function handleFileSelection(event) {
    const files = Array.from(event.target?.files || []);
    if (files.length === 0) {
        return;
    }

    for (const file of files) {
        try {
            const attachment = await loadAttachment(file);
            upsertAttachment(attachment);
        } catch (error) {
            console.error(error);
            setStatus(`${t('attach_failed_status', 'Unable to attach file.')} ${file.name}`.trim());
        }
    }
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderControlState(payload) {
    const metadata = payload?.metadata || {};
    const providerState = payload?.provider_state || metadata.provider_state || {};
    const availableProviders = payload?.available_providers || metadata.available_providers || [];
    const availableModels = payload?.available_models || metadata.available_models || [];
    const thinkEnabled = payload?.think_enabled ?? metadata.think_enabled ?? false;

    controlState.availableProviders = Array.isArray(availableProviders) ? availableProviders : [];
    controlState.availableModels = Array.isArray(availableModels) ? availableModels : [];
    controlState.selectedProvider = String(providerState.provider || controlState.selectedProvider || '');
    controlState.selectedModel = String(providerState.model || controlState.selectedModel || '');
    controlState.thinkEnabled = Boolean(thinkEnabled);

    providerSelectEl.innerHTML = controlState.availableProviders.map(provider => {
        if (typeof provider === 'string') {
            return `<option value="${escapeHtml(provider)}">${escapeHtml(provider)}</option>`;
        }
        const id = provider.id || provider.value || '';
        const label = provider.label || id;
        return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
    }).join('');

    if (controlState.selectedProvider) {
        providerSelectEl.value = controlState.selectedProvider;
    }

    modelOptionsEl.innerHTML = controlState.availableModels
        .map(model => `<option value="${escapeHtml(String(model))}"></option>`)
        .join('');
    modelInputEl.value = controlState.selectedModel;
    thinkToggleEl.checked = controlState.thinkEnabled;
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

function normalizeContentBlocks(content) {
    if (Array.isArray(content)) {
        return content;
    }
    if (content === null || content === undefined || content === '') {
        return [];
    }
    return [{ type: 'text', text: String(content) }];
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

function renderBlocksHtml(blocks) {
    return normalizeContentBlocks(blocks)
        .map(createContentBlockHtml)
        .join('');
}

function extractTextFromBlocks(blocks) {
    return normalizeContentBlocks(blocks)
        .map(block => {
            if (!block || typeof block !== 'object') {
                return '';
            }
            if (block.type === 'thinking') {
                return `${block.summary || t('thinking_trace_label', 'Thinking trace')}\n${block.text || ''}`.trim();
            }
            if (block.type === 'html') {
                return '';
            }
            return String(block.text || '').trim();
        })
        .filter(Boolean)
        .join('\n\n');
}

function extractTextFromHtml(html) {
    if (!html) {
        return '';
    }

    const container = document.createElement('div');
    container.innerHTML = html;
    return (container.textContent || '').trim();
}

function extractMarkdownFromBlocks(blocks) {
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

function getCurrentPlainText() {
    if (chatState.active) {
        return chatState.messages
            .map(message => {
                const role = String(message.role || 'assistant');
                const text = extractTextFromBlocks(message.content);
                return text ? `${role}: ${text}` : '';
            })
            .filter(Boolean)
            .join('\n\n');
    }

    return extractTextFromBlocks(displayState.blocks);
}

function getMessageById(messageId) {
    return chatState.messages.find(message => message?.id === messageId) || null;
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

function getCurrentCopyText() {
    if (viewState.mode === 'chat') {
        return getCurrentPlainText();
    }

    return copyText || getCurrentPlainText() || contentEl.textContent || '';
}

function getCurrentCopyMarkdown() {
    if (viewState.mode === 'chat') {
        return '';
    }

    return copyMarkdown || copyText || getCurrentPlainText() || contentEl.textContent || '';
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

function renderDisplayPayload(payload) {
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

    displayState.blocks = blocks;
    displayState.actions = Array.isArray(actions) ? actions : [];
    renderDisplayState();
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

function copyMessageText(messageId) {
    const message = getMessageById(messageId);
    if (!message) {
        return;
    }
    copyToClipboard(extractTextFromBlocks(message.content));
}

function copyMessageMarkdown(messageId) {
    const message = getMessageById(messageId);
    if (!message) {
        return;
    }
    copyToClipboard(extractMarkdownFromBlocks(message.content));
}

function copyMessageTable(messageId) {
    const messageEl = Array.from(contentEl.querySelectorAll('.chat-message'))
        .find(element => element instanceof HTMLElement && element.dataset.messageId === messageId);
    const tableEl = messageEl?.querySelector('table');
    if (!(tableEl instanceof HTMLTableElement)) {
        setStatus(t('copy_failed_status', 'Copy failed.'));
        return;
    }
    copyToClipboard(tableElementToMarkdown(tableEl));
}

function renderDisplayState() {
    viewState.mode = 'display';
    renderCurrentView();
}

function setDisplayText(text) {
    displayState.blocks = text ? [{ type: 'text', text }] : [];
    displayState.actions = [];
    renderDisplayState();
}

function renderChatState() {
    viewState.mode = 'chat';
    renderCurrentView();
    scrollChatToBottom();
}

function renderCurrentView() {
    if (viewState.mode === 'chat') {
        const html = chatState.messages.map(createChatMessageHtml).join('');
        contentEl.innerHTML = html || t('no_chat_messages', 'No chat messages available.');
        setChatPanelVisible(true);
        renderAttachments();
        return;
    }

    contentEl.innerHTML = `${renderBlocksHtml(displayState.blocks)}${createActionsHtml(displayState.actions)}`;
    setChatPanelVisible(false);
    renderAttachments();
}

function renderChatHistory(payload) {
    chatState.active = true;
    chatState.conversationId = payload.conversation_id || null;
    chatState.commandId = payload.command_id || chatState.commandId;
    chatState.messages = Array.isArray(payload.messages) ? payload.messages : [];
    renderChatState();
}

function appendChatMessage(payload) {
    if (!chatState.active) {
        chatState.active = true;
        setChatPanelVisible(true);
    }

    if (payload.conversation_id) {
        chatState.conversationId = payload.conversation_id;
    }
    if (payload.command_id) {
        chatState.commandId = payload.command_id;
    }

    const messages = Array.isArray(payload.messages)
        ? payload.messages
        : payload.message
        ? [payload.message]
        : [payload];

    messages.forEach(message => {
        if (message.id) {
            chatState.messages = chatState.messages.filter(m => m.id !== message.id);
        }
        chatState.messages.push(message);
    });

    renderChatState();
}

function updateChatMessage(payload) {
    const messageId = payload.message_id || payload.id;
    if (!messageId) {
        return;
    }

    if (payload.conversation_id) {
        chatState.conversationId = payload.conversation_id;
    }
    if (payload.command_id) {
        chatState.commandId = payload.command_id;
    }

    chatState.messages = chatState.messages.map(message =>
        message.id === messageId ? { ...message, content: payload.content || message.content } : message
    );
    renderChatState();
}

function resetChatState() {
    chatState.active = false;
    chatState.commandId = null;
    chatState.conversationId = null;
    chatState.messages = [];
    clearPendingAttachments();
}

function resetDisplayState() {
    displayState.blocks = [];
    displayState.actions = [];
}

function clearChat() {
    resetChatState();
    resetDisplayState();
    renderDisplayState();
}

function scrollChatToBottom() {
    contentEl.scrollTop = contentEl.scrollHeight;
}

function submitChatMessage() {
    if (!chatInputEl) {
        return;
    }

    const message = chatInputEl.value.trim();
    const attachments = Array.isArray(chatState.attachments) ? chatState.attachments : [];
    if (!message && attachments.length === 0) {
        return;
    }

    reportUiEvent('chat_submitted', chatState.commandId, {
        conversation_id: chatState.conversationId,
        message,
        attachments,
    });
    setStatus(t('submitted_status', 'Message submitted.'));
    chatInputEl.value = '';
    clearPendingAttachments();
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

function submitProviderSelection() {
    const provider = providerSelectEl.value.trim();
    if (!provider) {
        return;
    }
    controlState.selectedProvider = provider;
    reportUiEvent('provider_selected', currentCommandId, { provider });
}

function submitModelSelection() {
    const model = modelInputEl.value.trim();
    if (!model) {
        return;
    }
    controlState.selectedModel = model;
    reportUiEvent('model_selected', currentCommandId, {
        provider: providerSelectEl.value.trim() || null,
        model,
    });
}

function submitThinkModeToggle() {
    controlState.thinkEnabled = thinkToggleEl.checked;
    reportUiEvent('think_mode_toggled', currentCommandId, { enabled: thinkToggleEl.checked });
}

function handleResultActionClick(target) {
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

    reportUiEvent('ui_action_invoked', currentCommandId, { action_id: actionId, payload });
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        setStatus(t('copied_status', 'Copied to clipboard.'));
    }).catch(err => {
        setStatus(t('copy_failed_status', 'Copy failed.'));
        console.error(err);
    });
}

function handleOpenChatCommand(commandId, payload) {
    resetChatState();
    resetDisplayState();
    chatState.active = true;
    chatState.commandId = commandId;
    chatState.conversationId = payload.conversation_id || null;
    if (payload.initial_image_base64) {
        upsertAttachment({
            id: `initial-image-${Date.now()}`,
            kind: 'image',
            name: t('initial_image_name', 'Initial image'),
            mime_type: 'image/png',
            image_base64: payload.initial_image_base64,
        });
    }
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
        renderChatState();
    }
    copyText = payload.initial_text || '';
    copyMarkdown = payload.initial_text || '';
}

function handleSyncSessionCommand(payload) {
    if (payload.conversation_id) {
        chatState.conversationId = payload.conversation_id;
    }

    if (chatState.active) {
        renderChatState();
        return;
    }

    if (displayState.blocks.length > 0 || displayState.actions.length > 0) {
        renderDisplayState();
    }
}

function handleErrorCommand(payload) {
    clearChat();
    const errorMessage = payload.error_message || t('no_content', 'No content available.');
    const details = typeof payload.details === 'string' ? payload.details.trim() : '';
    const fullMessage = details ? `${errorMessage}\n\n${details}` : errorMessage;
    setDisplayText(`${t('error_prefix', 'Error')}: ${fullMessage}`);
    copyText = fullMessage;
    copyMarkdown = fullMessage;
}

function handleProgressCommand(payload) {
    clearChat();
    setDisplayText(`${t('progress_prefix', 'Progress')}: ${payload.message || t('progress_default_message', 'Working...')}`);
    copyText = payload.message || '';
    copyMarkdown = payload.message || '';
}

function handleCloseWindowCommand() {
    clearChat();
    setDisplayText(t('window_closed_message', 'Window closed by host command.'));
    copyText = '';
    copyMarkdown = '';
}

function handleHostEnvelope(envelope) {
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
    currentCommandId = commandId;
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
            copyText = payload.copy_text || payload.output_text || '';
            copyMarkdown = payload.copy_markdown || payload.output_text || '';
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

function setupWebViewBridge() {
    ensureSendHostEvent();
    if (window.chrome?.webview?.addEventListener) {
        window.chrome.webview.addEventListener('message', event => {
            let envelope;

            try {
                envelope = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
            } catch (err) {
                setStatus(t('parse_host_message_failed_status', 'Unable to parse host message.'));
                console.error('WebView host message parse error', err);
                reportUiFailure(null, 'invalid_json');
                return;
            }

            try {
                handleHostEnvelope(envelope);
            } catch (err) {
                setStatus(t('apply_host_command_failed_status', 'Unable to apply host command.'));
                console.error('WebView host message handling error', err, envelope);
                reportUiFailure(envelope?.correlation_id || envelope?.id || null, 'handler_error');
            }
        });
    } else {
        setStatus(t('bridge_unavailable_status', 'WebView bridge unavailable.'));
    }
}

chatSendEl?.addEventListener('click', submitChatMessage);
attachFilesEl?.addEventListener('click', () => fileInputEl?.click());
fileInputEl?.addEventListener('change', handleFileSelection);
providerSelectEl?.addEventListener('change', submitProviderSelection);
modelInputEl?.addEventListener('change', submitModelSelection);
modelInputEl?.addEventListener('blur', submitModelSelection);
thinkToggleEl?.addEventListener('change', submitThinkModeToggle);
chatInputEl?.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submitChatMessage();
    }
});
contentEl?.addEventListener('click', event => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
        return;
    }
    const copyTextButton = target.closest('[data-copy-message-text]');
    if (copyTextButton instanceof HTMLElement) {
        copyMessageText(copyTextButton.dataset.copyMessageText || '');
        return;
    }
    const copyMarkdownButton = target.closest('[data-copy-message-markdown]');
    if (copyMarkdownButton instanceof HTMLElement) {
        copyMessageMarkdown(copyMarkdownButton.dataset.copyMessageMarkdown || '');
        return;
    }
    const copyTableButton = target.closest('[data-copy-message-table]');
    if (copyTableButton instanceof HTMLElement) {
        copyMessageTable(copyTableButton.dataset.copyMessageTable || '');
        return;
    }
    const actionButton = target.closest('[data-action-id]');
    if (actionButton instanceof HTMLElement) {
        handleResultActionClick(actionButton);
    }
});
attachmentStripEl?.addEventListener('click', event => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
        return;
    }
    const attachmentId = target.dataset.removeAttachment;
    if (attachmentId) {
        removeAttachment(attachmentId);
    }
});

document.getElementById('copy-text').onclick = () => copyToClipboard(getCurrentCopyText());
document.getElementById('copy-markdown').onclick = () => copyToClipboard(getCurrentCopyMarkdown());
document.getElementById('clear').onclick = () => {
    clearChat();
    setStatus(t('content_cleared_status', 'Content cleared.'));
};
document.getElementById('close-window').onclick = () => requestCloseHost();
document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
        requestCloseHost();
    }
});

setupWebViewBridge();
applyLocalizedStrings({ localized_strings: localizedStrings });
