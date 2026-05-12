import { appState, t } from './state.svelte';

// ---------------------------------------------------------------------------
// HTML sanitization
// ---------------------------------------------------------------------------

const ALLOWED_TAGS = new Set([
	'a', 'article', 'aside', 'b', 'blockquote', 'br', 'caption', 'code',
	'dd', 'del', 'details', 'div', 'dl', 'dt', 'em', 'figcaption', 'figure',
	'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'kbd', 'li',
	'main', 'ol', 'p', 'pre', 's', 'section', 'small', 'span', 'strong',
	'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead',
	'tr', 'u', 'ul',
]);

const ALLOWED_ATTRIBUTES = new Set([
	'alt', 'aria-label', 'aria-labelledby', 'aria-describedby',
	'class', 'colspan', 'href', 'role', 'rowspan', 'scope', 'src',
	'target', 'title',
]);

function isSafeUrl(attributeName: string, value: string): boolean {
	const normalized = String(value || '').trim().toLowerCase();
	if (!normalized) return true;
	if (attributeName === 'href') {
		return (
			normalized.startsWith('#') ||
			normalized.startsWith('http://') ||
			normalized.startsWith('https://') ||
			normalized.startsWith('mailto:')
		);
	}
	if (attributeName === 'src') {
		return (
			normalized.startsWith('http://') ||
			normalized.startsWith('https://') ||
			normalized.startsWith('data:image/')
		);
	}
	return true;
}

export function sanitizeHtml(html: string | null | undefined): string {
	if (!html) return '';

	const parser = new DOMParser();
	const doc = parser.parseFromString(html, 'text/html');

	function walk(node: Node): string {
		if (node.nodeType === Node.TEXT_NODE) {
			return node.textContent || '';
		}

		if (node.nodeType !== Node.ELEMENT_NODE) return '';

		const el = node as Element;
		const tagName = el.tagName.toLowerCase();

		if (!ALLOWED_TAGS.has(tagName)) {
			let result = '';
			for (const child of Array.from(el.childNodes)) {
				result += walk(child);
			}
			return result;
		}

		const attrs: string[] = [];
		for (const attr of Array.from(el.attributes)) {
			const attrName = attr.name.toLowerCase();
			if (
				ALLOWED_ATTRIBUTES.has(attrName) &&
				isSafeUrl(attrName, attr.value)
			) {
				attrs.push(`${attrName}="${attr.value.replace(/"/g, '&quot;')}"`);
			}
		}

		let inner = '';
		for (const child of Array.from(el.childNodes)) {
			inner += walk(child);
		}

		const attrStr = attrs.length > 0 ? ' ' + attrs.join(' ') : '';

		if (tagName === 'img' || tagName === 'br' || tagName === 'hr') {
			return `<${tagName}${attrStr} />`;
		}

		return `<${tagName}${attrStr}>${inner}</${tagName}>`;
	}

	let result = '';
	for (const child of Array.from(doc.body.childNodes)) {
		result += walk(child);
	}
	return result;
}

// ---------------------------------------------------------------------------
// Content block helpers
// ---------------------------------------------------------------------------

export interface NormalizedBlock {
	type: string;
	text?: string;
	html?: string;
	[key: string]: unknown;
}

export function normalizeContentBlocks(content: unknown): NormalizedBlock[] {
	if (Array.isArray(content)) return content as NormalizedBlock[];
	if (typeof content === 'string') return [{ type: 'text', text: content }];
	return [];
}

export function extractTextFromBlocks(content: unknown): string {
	return normalizeContentBlocks(content)
		.filter((b) => b.type === 'text' && typeof b.text === 'string')
		.map((b) => b.text!)
		.join('\n')
		.trim();
}

export function extractMarkdownFromBlocks(content: unknown): string {
	return normalizeContentBlocks(content)
		.filter((b) => {
			if (b.type === 'text' && typeof b.text === 'string') return true;
			if (b.type === 'html' && typeof b.html === 'string') return true;
			return false;
		})
		.map((b) => {
			if (b.type === 'html') return tableHtmlToMarkdown(b.html || '') || b.html || '';
			return b.text || '';
		})
		.join('\n\n')
		.trim();
}

export function hasRenderedTables(content: unknown): boolean {
	return normalizeContentBlocks(content).some(
		(b) => b.type === 'html' && /<table[\s>]/i.test(b.html || ''),
	);
}

export function tableHtmlToMarkdown(html: string): string {
	if (!html) return '';
	try {
		const doc = new DOMParser().parseFromString(html, 'text/html');
		const table = doc.querySelector('table');
		if (!table) return '';

		const rows: string[][] = [];
		for (const tr of Array.from(table.querySelectorAll('tr'))) {
			const cells: string[] = [];
			for (const cell of Array.from(tr.querySelectorAll('th, td'))) {
				cells.push((cell.textContent || '').trim());
			}
			if (cells.length > 0) rows.push(cells);
		}

		if (rows.length === 0) return '';

		const colCount = Math.max(...rows.map((r) => r.length));
		const normalized = rows.map((r) => {
			while (r.length < colCount) r.push('');
			return r;
		});

		const lines: string[] = [];
		lines.push('| ' + normalized[0].join(' | ') + ' |');
		lines.push('| ' + normalized[0].map(() => '---').join(' | ') + ' |');
		for (let i = 1; i < normalized.length; i++) {
			lines.push('| ' + normalized[i].join(' | ') + ' |');
		}

		return lines.join('\n');
	} catch {
		return '';
	}
}

export function formatRoleLabel(role: string): string {
	switch ((role || '').toLowerCase()) {
		case 'assistant':
			return t('role_assistant', 'AI Assistant');
		case 'user':
			return t('role_user', 'You');
		case 'system':
			return t('role_system', 'System');
		default:
			return role || t('role_unknown', 'Unknown');
	}
}

// ---------------------------------------------------------------------------
// Copy buffer accessors
// ---------------------------------------------------------------------------

export function getCurrentCopyText(): string {
	return appState.copy.text || extractTextFromBlocks(appState.display.blocks) || '';
}

export function getCurrentCopyMarkdown(): string {
	return (
		appState.copy.markdown ||
		extractMarkdownFromBlocks(appState.display.blocks) ||
		''
	);
}
