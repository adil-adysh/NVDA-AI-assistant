## v0.5.1 - 2026-04-11
- Refactored add-on logging to use NVDA `logHandler` across core AI assistant modules.
- Improved tool-call and streaming diagnostics for more reliable assistant behavior.

## v0.5.0 - 2026-04-11
- Added a unified AI assistant command layer with a single main shortcut: `NVDA+Shift+A`.
- Added layer commands for summary, image description, chat, page-content chat, screenshot chat, and help.
- Added a new AI chat dialog with conversation history, tool calling support, and image/page context startup.
- Improved Ollama response extraction and image description prompt behavior for more reliable multimodal results.
- Refactored provider handling, chat coordination, and request metrics reporting.

## v0.4 - 2026-04-10
- Refactored the global plugin into focused modules for URL detection and bookmark management.
- Added on-demand current-page summarization through a local Ollama instance.
- Added bounded page text extraction and asynchronous summary delivery so NVDA remains responsive.
- Added user-facing documentation for the summary gesture and Ollama configuration.
