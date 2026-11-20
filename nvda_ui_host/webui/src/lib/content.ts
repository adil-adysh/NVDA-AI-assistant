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

function parseHtml(html: string): Document | null {
	try {
		return new DOMParser().parseFromString(html, 'text/html');
	} catch {
		return null;
	}
}

function normalizeCopiedText(text: string): string {
	return text
		.replace(/[ \t]+\n/g, '\n')
		.replace(/\n[ \t]+\n/g, '\n\n')
		.replace(/\n{3,}/g, '\n\n')
		.trim();
}

function plainTextFromNode(node: Node): string {
	if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || '';
	if (!(node instanceof Element)) return '';

	const tag = node.tagName.toLowerCase();
	if (tag === 'script' || tag === 'style' || tag === 'noscript') return '';
	if (tag === 'br') return '\n';
	if (tag === 'img') return node.getAttribute('alt') || '';
	if (tag === 'pre') {
		return `${(node.textContent || '').replace(/\r\n?/g, '\n').replace(/\n+$/, '')}\n\n`;
	}
	if (tag === 'table') {
		const rows = Array.from(node.querySelectorAll('tr'))
			.map((row) =>
				Array.from(row.querySelectorAll(':scope > th, :scope > td'))
					.map((cell) => normalizeCopiedText(plainTextFromNode(cell)))
					.join('\t'),
			)
			.filter(Boolean)
			.join('\n');
		return rows ? `\n\n${rows}\n\n` : '';
	}

	const content = Array.from(node.childNodes).map(plainTextFromNode).join('');
	if (tag === 'li') {
		const parent = node.parentElement;
		const parentTag = parent?.tagName.toLowerCase();
		const itemIndex = Array.from(parent?.children || []).indexOf(node);
		const parsedStart = Number.parseInt(parent?.getAttribute('start') || '1', 10);
		const start = Number.isNaN(parsedStart) ? 1 : parsedStart;
		const itemNumber = Number.parseInt(node.getAttribute('value') || '', 10);
		const marker = parentTag === 'ol' ? `${Number.isNaN(itemNumber) ? start + itemIndex : itemNumber}. ` : '• ';
		return `${marker}${content.trim()}\n`;
	}
	if (/^(p|div|section|article|h[1-6]|blockquote|pre|ul|ol)$/.test(tag)) {
		return `${content.trim()}\n\n`;
	}
	return content;
}

/** Convert rendered HTML into readable text while retaining useful block boundaries. */
export function htmlToPlainText(html: string): string {
	const doc = parseHtml(html);
	return doc ? normalizeCopiedText(plainTextFromNode(doc.body)) : '';
}

function escapeMarkdownText(text: string): string {
	return text
		.replace(/([\\`*_{}\[\]|#+!>~-])/g, '\\$1')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
}

function inlineCodeMarkdown(code: string): string {
	const backtickRuns = code.match(/`+/g) || [];
	const fence = '`'.repeat(Math.max(1, ...backtickRuns.map((run) => run.length + 1)));
	const needsPadding = code.length > 0 && (/^`|`$|^ | $/.test(code));
	const content = needsPadding ? ` ${code} ` : code;
	return `${fence}${content}${fence}`;
}

function markdownInline(node: Node): string {
	if (node.nodeType === Node.TEXT_NODE) return escapeMarkdownText(node.nodeValue || '');
	if (!(node instanceof Element)) return '';

	const tag = node.tagName.toLowerCase();
	if (tag === 'script' || tag === 'style' || tag === 'noscript') return '';
	if (tag === 'br') return '  \n';
	if (tag === 'code') return inlineCodeMarkdown(node.textContent || '');
	const children = Array.from(node.childNodes).map(markdownInline).join('');
	switch (tag) {
		case 'strong':
		case 'b':
			return children ? `**${children}**` : '';
		case 'em':
		case 'i':
			return children ? `*${children}*` : '';
		case 'del':
		case 's':
		case 'strike':
			return children ? `~~${children}~~` : '';
		case 'a': {
			const href = node.getAttribute('href') || '';
			return href ? `[${children}](${href.replace(/[()]/g, '\\$&')})` : children;
		}
		case 'img': {
			const alt = node.getAttribute('alt') || '';
			const src = node.getAttribute('src') || '';
			return src
				? `![${escapeMarkdownText(alt)}](${src.replace(/[()]/g, '\\$&')})`
				: escapeMarkdownText(alt);
		}
		default:
			return children;
	}
}

function markdownList(list: Element, depth = 0): string {
	const ordered = list.tagName.toLowerCase() === 'ol';
	const parsedStart = Number.parseInt(list.getAttribute('start') || '1', 10);
	let number = Number.isNaN(parsedStart) ? 1 : parsedStart;
	const lines: string[] = [];
	for (const item of Array.from(list.children).filter((child) => child.tagName.toLowerCase() === 'li')) {
		const itemValue = Number.parseInt(item.getAttribute('value') || '', 10);
		if (ordered && !Number.isNaN(itemValue)) number = itemValue;
		let inline = '';
		const nested: string[] = [];
		for (const child of Array.from(item.childNodes)) {
			if (child instanceof Element && ['ul', 'ol'].includes(child.tagName.toLowerCase())) {
				nested.push(markdownList(child, depth + 1));
			} else {
				inline += markdownInline(child);
			}
		}
		const marker = ordered ? `${number++}.` : '-';
		lines.push(`${'  '.repeat(depth)}${marker} ${inline.trim()}`);
		lines.push(...nested);
	}
	return lines.join('\n');
}

function markdownFromNode(node: Node): string {
	if (node.nodeType === Node.TEXT_NODE) return escapeMarkdownText(node.nodeValue || '');
	if (!(node instanceof Element)) return '';

	const tag = node.tagName.toLowerCase();
	if (tag === 'script' || tag === 'style' || tag === 'noscript') return '';
	if (tag === 'table') return `\n\n${tableHtmlToMarkdown(node.outerHTML)}\n\n`;
	if (tag === 'ul' || tag === 'ol') return `\n\n${markdownList(node)}\n\n`;
	if (/^h[1-6]$/.test(tag)) {
		const level = Number(tag.slice(1));
		return `\n\n${'#'.repeat(level)} ${markdownInline(node).trim()}\n\n`;
	}
	if (tag === 'p') return `\n\n${Array.from(node.childNodes).map(markdownInline).join('').trim()}\n\n`;
	if (tag === 'blockquote') {
		const quoted = markdownChildren(node.childNodes).trim();
		return `\n\n${quoted.split('\n').map((line) => `> ${line}`).join('\n')}\n\n`;
	}
	if (tag === 'pre') {
		const code = node.querySelector('code');
		const language = code?.className.match(/(?:^|\s)language-([\w+-]+)/)?.[1] || '';
		const content = code?.textContent ?? node.textContent ?? '';
		const backtickRuns = content.match(/`+/g) || [];
		const fence = '`'.repeat(Math.max(3, ...backtickRuns.map((run) => run.length + 1)));
		return `\n\n${fence}${language}\n${content.replace(/\n+$/, '')}\n${fence}\n\n`;
	}
	if (tag === 'hr') return '\n\n---\n\n';
	if (/^(div|section|article)$/.test(tag)) {
		return `\n\n${markdownChildren(node.childNodes).trim()}\n\n`;
	}
	return markdownInline(node);
}

function markdownChildren(nodes: NodeListOf<ChildNode> | NodeList): string {
	return Array.from(nodes)
		.filter(
			(node) =>
				node.nodeType !== Node.TEXT_NODE ||
				!(/\r|\n/.test(node.nodeValue || '') && !(node.nodeValue || '').trim()),
		)
		.map(markdownFromNode)
		.join('');
}

/** Convert rendered HTML to Markdown when the original Markdown source is unavailable. */
export function htmlToMarkdown(html: string): string {
	const doc = parseHtml(html);
	if (!doc) return '';
	return markdownChildren(doc.body.childNodes)
		.replace(/\n{3,}/g, '\n\n')
		.trim();
}

export function extractTextFromBlocks(content: unknown): string {
	return normalizeContentBlocks(content)
		.filter((b) => {
			if (b.type === 'text' && typeof b.text === 'string') return true;
			if (b.type === 'html' && typeof b.html === 'string') return true;
			return false;
		})
		.map((b) => {
			if (b.type === 'html') return htmlToPlainText(b.html || '');
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
			if (b.type === 'html') return htmlToMarkdown(b.html || '');
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
				cells.push(escapeMarkdownText((cell.textContent || '').replace(/\s+/g, ' ').trim()));
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
	return appState.copy.text?.trim()
		? appState.copy.text
		: extractTextFromBlocks(appState.display.blocks);
}

export function getCurrentCopyMarkdown(): string {
	return appState.copy.markdown?.trim()
		? appState.copy.markdown
		: extractMarkdownFromBlocks(appState.display.blocks);
}
