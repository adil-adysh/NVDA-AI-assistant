# Copy text and Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all result and chat copy actions produce the plain-text or Markdown format their labels promise.

**Architecture:** Keep conversion in the WebView content layer, which owns every copy action and can inspect rendered HTML. Preserve explicit source buffers when present; derive missing formats from display blocks, and omit role headings from copied chat message bodies.

**Tech Stack:** Svelte 5, TypeScript, browser `DOMParser`, existing WebView clipboard actions.

**Spec:** `docs/superpowers/specs/2026-11-20-copy-formats-design.md`

## Global Constraints

- Do not add a runtime dependency solely for conversion.
- HTML-only blocks must not be copied as raw HTML.
- Preserve explicit source Markdown when present.
- Do not alter chat display or the existing copy-table action.
- Keep user-visible behavior changes within the WebView content and action layers unless inspection shows another boundary is required.

## Review Focus

- Empty explicit copy buffers must fall back to rendered blocks, not raw one-shot Markdown.
- HTML paragraphs and line breaks must remain separated in plain text.
- HTML nested lists, inline formatting, links, code, blockquotes, and tables must produce usable Markdown.
- Raw text blocks must remain unchanged when no HTML representation exists.
- HTML-only and table-bearing chat history must copy without leaking HTML tags.

---

### Task 1: Convert rendered HTML to plain text and Markdown

**Files:**
- Modify: `nvda_ui_host/webui/src/lib/content.ts`

**Interfaces:**
- Add `htmlToPlainText(html: string): string` for block-aware text extraction.
- Add `htmlToMarkdown(html: string): string` for supported semantic HTML elements.
- Keep `extractTextFromBlocks(content)` and `extractMarkdownFromBlocks(content)` as the shared block APIs; route HTML blocks through the new converters.
- Keep `tableHtmlToMarkdown(html)` available for the dedicated table action.

- [ ] Implement `htmlToPlainText` to preserve paragraph, heading, list, line-break, and table boundaries while returning text rather than tags.
- [ ] Implement `htmlToMarkdown` for headings, paragraphs, emphasis, links, inline/fenced code, lists, blockquotes, and tables; return readable text when an element has no Markdown-specific representation.
- [ ] Update the shared extractors so HTML blocks use these conversions and raw text blocks keep their current content.

### Task 2: Route copy actions through format-specific extraction

**Files:**
- Modify: `nvda_ui_host/webui/src/lib/commands/render-display.ts`
- Modify: `nvda_ui_host/webui/src/lib/actions.ts`
- Modify: `nvda_ui_host/webui/src/lib/content.ts` (copy buffer accessors)

**Interfaces:**
- `getCurrentCopyText()` and `getCurrentCopyMarkdown()` remain the toolbar accessors.
- Chat `copyMessageText(message)` and `copyMessageMarkdown(message)` copy only the message body.

- [ ] Set result copy buffers only from explicit `copy_text` and `copy_markdown` fields; derive missing values from rendered blocks rather than `output_text` fallback.
- [ ] Keep explicit Markdown source authoritative; fall back to `extractMarkdownFromBlocks` for HTML-only results and chat history.
- [ ] Remove the role heading from `copyMessageMarkdown` output while preserving the existing dedicated table copy action.

## Validation

No automated tests will be added or run for this task unless requested. Review the diff for consistency across result and chat call paths; do not claim runtime verification.
