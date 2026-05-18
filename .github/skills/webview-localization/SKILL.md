---
name: webview-localization
description: "**UTILITY SKILL** — Add or change translator-facing WebView UI labels, debug missing POT entries, or move label ownership from JS/Rust to Python. USE FOR: translatable WebView labels; missing msgid in POT; moving label ownership to Python; translator comments; gettext extraction. DO NOT USE FOR: implementing features; non-WebView i18n; Rust/JS logic. INVOKES: file reads (session_state.py, buildVars.py, gettexttool), terminal (xgettext, npm build, ruff). FOR SINGLE OPERATIONS: add the string directly."
---

# WebView Localization

Python owns translator-facing WebView labels; Rust transports, Web UI renders `localized_strings`.

## Key Files

`session_state.py`, `buildVars.py`, `gettexttool/__init__.py`, `state.svelte.ts`, `docs/ui-host-protocol.md`

## Workflow

1. Identify where the label lives (Python, Rust, or Web UI).
2. Move WebView labels to Python via `localized_strings` in session/result metadata.
3. Add `# TRANSLATORS:` comment above strings whose purpose isn't obvious.
4. Ensure the file is in `buildVars.i18nSources` and uses `translate(...)` keyword.
5. Remove redundant browser-owned defaults when Python supplies the same label.
6. Update `docs/ui-host-protocol.md` if the localization flow crosses protocol boundary.

## Hints

- Controls, headings, toolbar/attachment labels, status notices → Python.
- Temporary browser-only fallback → keep minimal.
- Missing from POT → check `gettexttool/__init__.py`, then `buildVars.i18nSources`, then source call shape.
- Extend `localized_strings`; don't invent a second label source.

## Validation

- `xgettext` against relevant Python files for extraction.
- `npm --prefix nvda_ui_host run build:webui` after Web UI changes.
- `python -m ruff check .` for Python changes.
- If protocol changed, validate docs + Python producer together.
