import { appState, t } from './state.svelte';

// ── Sanitizer disabled ──────────────────────────────────────────────
// HTML from the Python side is considered trusted (goes through
// Python-Markdown which may pass raw HTML). If sanitization is needed
// in the future, restore the tag/attribute allowlists below and
// re-implement sanitizeHtml() with DOMParser-based filtering.
// ────────────────────────────────────────────────────────────────────

export function sanitizeHtml(html: string | null | undefined): string {
	if (!html) return '';
	return html;
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
		.filter((b) => {
			if (b.type === 'text' && typeof b.text === 'string') return true;
			if (b.type === 'html' && typeof b.html === 'string') return true;
			return false;
		})
		.map((b) => {
			if (b.type === 'html') {
				try {
					const doc = new DOMParser().parseFromString(b.html || '', 'text/html');
					return doc.body.textContent || '';
				} catch {
					return '';
				}
			}
			return b.text || '';
		})
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

/** Keep announcements useful without making NVDA read an entire answer twice. */
export function summarizeForAnnouncement(content: unknown, maxLength = 280): string {
	const text = extractTextFromBlocks(content).replace(/\s+/g, ' ').trim();
	if (!text) return '';
	if (text.length <= maxLength) return text;
	return `${text.slice(0, maxLength).trimEnd()}…`;
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
