import { appState, setPendingFocus, setStatus, t } from './state.svelte.js';

const SUPPORTED_IMAGE_EXTENSIONS = new Set([
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg',
]);

const TEXT_FILE_EXTENSIONS = new Set([
    'txt', 'md', 'markdown', 'json', 'yaml', 'yml', 'csv', 'tsv', 'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'htm', 'xml', 'css', 'scss', 'less', 'java', 'c', 'cpp', 'h', 'hpp', 'rs', 'go', 'rb', 'php', 'sql', 'log',
]);

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

function getFileExtension(file) {
    const parts = file.name.toLowerCase().split('.');
    return parts.length > 1 ? parts.pop() || '' : '';
}

function isSupportedImageFile(file) {
    if (file.type && file.type.startsWith('image/')) {
        return true;
    }

    const extension = getFileExtension(file);
    return SUPPORTED_IMAGE_EXTENSIONS.has(extension);
}

function isTextFile(file) {
    if (file.type && file.type.startsWith('text/')) {
        return true;
    }

    const extension = getFileExtension(file);
    return TEXT_FILE_EXTENSIONS.has(extension || '');
}

async function loadAttachment(file) {
    const attachmentId = createAttachmentId(file);

    if (!isSupportedImageFile(file)) {
        throw new Error(`Unsupported image type for ${file.name}`);
    }

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

export function upsertAttachment(attachment) {
    appState.chat.attachments = appState.chat.attachments.filter(item => item.id !== attachment.id);
    appState.chat.attachments.push(attachment);
}

export function removeAttachment(attachmentId) {
    appState.chat.attachments = appState.chat.attachments.filter(item => item.id !== attachmentId);
    setPendingFocus('composer');
}

export function clearPendingAttachments(fileInputElement = null) {
    appState.chat.attachments = [];

    if (fileInputElement) {
        fileInputElement.value = '';
    }
}

export function addInitialImageAttachment(base64) {
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

export async function handleFileSelection(fileList) {
    const files = Array.from(fileList || []);
    if (files.length === 0) {
        return;
    }

    for (const file of files) {
        try {
            const attachment = await loadAttachment(file);
            upsertAttachment(attachment);
            setStatus(`${t('attach_button', 'Upload image')}: ${file.name}`, true);
        } catch (error) {
            console.error(error);
            const errorMessage = error instanceof Error ? error.message : String(error);
            setStatus(`${t('attach_failed_status', 'Unable to attach image.')} ${errorMessage}`.trim(), true);
        }
    }

    setPendingFocus('composer');
}
