import { attachmentStripEl, fileInputEl } from './dom.js';
import { t } from './localization.js';
import { appState } from './state.js';
import { escapeHtml, setStatus } from './utils.js';

const TEXT_FILE_EXTENSIONS = new Set([
    'txt', 'md', 'markdown', 'json', 'yaml', 'yml', 'csv', 'tsv', 'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'htm', 'xml', 'css', 'scss', 'less', 'java', 'c', 'cpp', 'h', 'hpp', 'rs', 'go', 'rb', 'php', 'sql', 'log',
]);

export function renderAttachments() {
    if (!attachmentStripEl) {
        return;
    }

    if (appState.viewState.mode !== 'chat') {
        attachmentStripEl.innerHTML = '';
        return;
    }

    if (!Array.isArray(appState.chatState.attachments) || appState.chatState.attachments.length === 0) {
        attachmentStripEl.innerHTML = '';
        return;
    }

    attachmentStripEl.innerHTML = appState.chatState.attachments.map(attachment => `
        <div class="attachment-chip" data-attachment-id="${escapeHtml(attachment.id || '')}">
            <span>${escapeHtml(attachment.name || attachment.kind || t('attachment_fallback_name', 'Attachment'))}</span>
            <button type="button" data-remove-attachment="${escapeHtml(attachment.id || '')}">${escapeHtml(t('remove_attachment', 'Remove'))}</button>
        </div>
    `).join('');
}

export function clearPendingAttachments() {
    appState.chatState.attachments = [];
    renderAttachments();
    if (fileInputEl) {
        fileInputEl.value = '';
    }
}

export function upsertAttachment(attachment) {
    appState.chatState.attachments = appState.chatState.attachments.filter(item => item.id !== attachment.id);
    appState.chatState.attachments.push(attachment);
    renderAttachments();
}

export function removeAttachment(attachmentId) {
    appState.chatState.attachments = appState.chatState.attachments.filter(item => item.id !== attachmentId);
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

export async function handleFileSelection(event) {
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
