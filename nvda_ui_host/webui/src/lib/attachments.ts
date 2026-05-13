import { appState, setPendingFocus, setStatus, t } from './state.svelte';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SUPPORTED_IMAGE_EXTENSIONS = new Set([
	'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg',
]);

const TEXT_FILE_EXTENSIONS = new Set([
	'txt', 'md', 'markdown', 'json', 'yaml', 'yml', 'csv', 'tsv',
	'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'htm', 'xml',
	'css', 'scss', 'less', 'java', 'c', 'cpp', 'h', 'hpp',
	'rs', 'go', 'rb', 'php', 'sql', 'log',
]);

// ---------------------------------------------------------------------------
// Attachment types
// ---------------------------------------------------------------------------

interface Attachment {
	id: string;
	name?: string;
	kind?: string;
	image_base64?: string;
	mime_type?: string;
	text_content?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createAttachmentId(file: File): string {
	return `attachment-${Date.now()}-${Math.random().toString(36).slice(2, 8)}-${file.name}`;
}

function readFileAsDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ''));
		reader.onerror = () =>
			reject(reader.error || new Error('Unable to read file as data URL'));
		reader.readAsDataURL(file);
	});
}

function readFileAsText(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ''));
		reader.onerror = () =>
			reject(reader.error || new Error('Unable to read file as text'));
		reader.readAsText(file);
	});
}

function getFileExtension(file: File): string {
	const parts = file.name.toLowerCase().split('.');
	return parts.length > 1 ? parts.pop() || '' : '';
}

function isSupportedImageFile(file: File): boolean {
	if (file.type && file.type.startsWith('image/')) return true;
	const extension = getFileExtension(file);
	return SUPPORTED_IMAGE_EXTENSIONS.has(extension);
}

function isTextFile(file: File): boolean {
	if (file.type && file.type.startsWith('text/')) return true;
	const extension = getFileExtension(file);
	return TEXT_FILE_EXTENSIONS.has(extension || '');
}

async function loadAttachment(file: File): Promise<Attachment> {
	const attachmentId = createAttachmentId(file);

	if (!isSupportedImageFile(file)) {
		throw new Error(`Unsupported image type for ${file.name}`);
	}

	const dataUrl = await readFileAsDataUrl(file);
	const [mimeType, base64] = dataUrl.split(',');
	const extractedMime = mimeType ? mimeType.replace('data:', '').replace(';base64', '') : '';

	return {
		id: attachmentId,
		name: file.name,
		kind: 'image',
		image_base64: base64 || '',
		mime_type: extractedMime || file.type || 'image/png',
	};
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function handleFileSelection(fileList: FileList | null): Promise<void> {
	if (!fileList || fileList.length === 0) return;

	const files = Array.from(fileList);
	const attachments: Attachment[] = [];

	for (const file of files) {
		try {
			const attachment = await loadAttachment(file);
			attachments.push(attachment);
		} catch (error) {
			console.error('Failed to load attachment:', error);
			setStatus(
				t('attachment_load_failed', 'Failed to load {file_name}').replace('{file_name}', file.name),
				true,
			);
		}
	}

	if (attachments.length > 0) {
		appState.chat.attachments = [...appState.chat.attachments, ...attachments];
		setStatus(
			t('attachments_added_status', '{count} attachment(s) added.').replace('{count}', String(attachments.length)),
			true,
		);
		setPendingFocus('composer');
	}
}

export function removeAttachment(attachmentId: string): void {
	appState.chat.attachments = appState.chat.attachments.filter(
		(a) => a.id !== attachmentId,
	);
}

export function clearPendingAttachments(fileInputElement: HTMLInputElement | null = null): void {
	appState.chat.attachments = [];
	if (fileInputElement) {
		fileInputElement.value = '';
	}
}

export function addInitialImageAttachment(base64: string | null | undefined): void {
	if (!base64) return;

	appState.chat.attachments = [
		...appState.chat.attachments,
		{
			id: `initial-image-${Date.now()}`,
			name: 'image.png',
			kind: 'image',
			image_base64: base64,
			mime_type: 'image/png',
		},
	];
}
