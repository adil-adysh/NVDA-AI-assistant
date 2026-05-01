import { appState, t } from './state.svelte.js';

export function normalizeContentBlocks(content) {
    if (Array.isArray(content)) {
        return content;
    }

    if (content === null || content === undefined || content === '') {
        return [];
    }

    return [{ type: 'text', text: String(content) }];
}

export function extractTextFromHtml(html) {
    if (!html) {
        return '';
    }

    const documentFragment = new DOMParser().parseFromString(html, 'text/html');
    return (documentFragment.body.textContent || '').trim();
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

            if (block.type === 'image') {
                return String(block.alt || t('image_attachment_notice', '[Image attachment included]')).trim();
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

            if (block.type === 'image') {
                return String(block.alt || t('image_attachment_notice', '[Image attachment included]')).trim();
            }

            return String(block.text || '').trim();
        })
        .filter(Boolean)
        .join('\n\n');
}

export function formatRoleLabel(role) {
    const value = String(role || 'assistant').trim().toLowerCase();

    if (value === 'user') {
        return t('user_heading', 'User prompt');
    }

    if (value === 'assistant') {
        return t('assistant_heading', 'Assistant response');
    }

    return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : t('assistant_heading', 'Assistant response');
}

export function buildChatMarkdownTranscript() {
    return appState.chat.messages
        .map((message, index) => {
            if (!message) {
                return '';
            }

            const roleLabel = formatRoleLabel(message.role || 'assistant');
            const heading = index % 2 === 0 ? '#####' : '######';
            const body = extractMarkdownFromBlocks(message.content);
            return body ? `${heading} ${roleLabel}\n\n${body}` : `${heading} ${roleLabel}`;
        })
        .filter(Boolean)
        .join('\n\n');
}

export function getCurrentPlainText() {
    if (appState.view.mode === 'chat') {
        return appState.chat.messages
            .map(message => {
                const roleLabel = formatRoleLabel(message.role || 'assistant');
                const text = extractTextFromBlocks(message.content);
                return text ? `${roleLabel}: ${text}` : '';
            })
            .filter(Boolean)
            .join('\n\n');
    }

    return extractTextFromBlocks(appState.display.blocks);
}

export function getCurrentCopyText() {
    if (appState.view.mode === 'chat') {
        return getCurrentPlainText();
    }

    return appState.copy.text || getCurrentPlainText();
}

export function getCurrentCopyMarkdown() {
    if (appState.view.mode === 'chat') {
        return buildChatMarkdownTranscript() || getCurrentPlainText();
    }

    return appState.copy.markdown || extractMarkdownFromBlocks(appState.display.blocks) || appState.copy.text || getCurrentPlainText();
}

export function hasRenderedTables(blocks) {
    return normalizeContentBlocks(blocks).some(block => block?.type === 'html' && /<table[\s>]/i.test(block.html || ''));
}

function escapeMarkdownCell(text) {
    return String(text || '').replace(/\|/g, '\\|').replace(/\r?\n/g, '<br>');
}

export function tableHtmlToMarkdown(html) {
    if (!html) {
        return '';
    }

    const documentFragment = new DOMParser().parseFromString(html, 'text/html');
    const tableElement = documentFragment.querySelector('table');

    if (!(tableElement instanceof HTMLTableElement)) {
        return '';
    }

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
