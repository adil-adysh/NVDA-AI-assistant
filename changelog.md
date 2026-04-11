## v0.5.3 - 2026-04-11
- Added real-time provider title updates in the open chat window when switching between Ollama and Gemini.
- Implemented canonical chat message and tool handling for more reliable provider request payloads and tool invocation flow.
- Improved Gemini and Ollama tool-call serialization, provider state management, and debug logging.

## v0.5.2 - 2026-04-11
- Fixed Gemini streaming payload serialization by normalizing Gemini `contents` and `tools` request shapes.
- Improved Gemini streaming and debug logging to make request flow and tool-call behavior visible.
- Aligned Gemini chat and stream endpoints with the official API examples.

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
