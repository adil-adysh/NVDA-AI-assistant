# Copy text and Markdown behavior

## Intent

Make every copy action match its label across one-shot results and chat. “Copy text” copies readable content without HTML markup, while “Copy Markdown” copies Markdown source or a Markdown representation of rendered HTML. Chat copy actions copy only the selected message body.

## Approaches

- **WebView-owned extraction (selected):** retain source Markdown when supplied and otherwise convert the rendered HTML blocks at copy time. This keeps copy behavior in the UI layer that owns all copy actions and supports future content blocks without adding duplicate conversion paths to Python.
- **Python-generated variants:** prepare plain text and Markdown for every result and transport both. This centralizes conversion on the Python side but duplicates transport state and does not cover chat history or content produced solely in the WebView.
- **Keep current fallback behavior:** use text fields directly. This is simple, but copies Markdown as plain text in one-shot results and raw HTML as Markdown in chat history.

## Scope and constraints

- Use existing `copy_text` and `copy_markdown` values as authoritative when present; derive missing values from display blocks.
- Plain-text extraction from HTML should retain useful paragraph, list, and table boundaries while excluding tags.
- Markdown extraction should cover rendered headings, paragraphs, emphasis, links, code, lists, blockquotes, and tables. HTML-only blocks must not be copied as raw HTML.
- Text blocks retain their existing text content. Image and thinking blocks are excluded from copy output unless their text is part of the user-visible answer.
- Do not add a runtime dependency solely for conversion.
- Keep changes in the WebView content/action layer and its call sites; no protocol changes are expected.

## Acceptance

- One-shot “Copy text” and chat “Copy response” contain readable text without HTML tags.
- “Copy Markdown” actions return Markdown, never raw HTML, preserving original Markdown when supplied.
- Copying a chat response does not prepend a role heading.
- Existing table-copy behavior remains available and produces a Markdown table.
