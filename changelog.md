# Changelog

All notable changes to this project will be documented in this file.

---

## v0.5.5 - 2026-04-14

### Features

* Added candidate providers for browser, terminal, and text editor contexts to improve contextual extraction coverage.

### Improvements

* Enhanced extraction context handling to make page, terminal, and editor content more reliable for AI prompt construction.
* Improved the assistant's ability to determine the correct active source for browser, terminal, and text editor inputs.

---

## v0.5.4 - 2026-04-12

### Features

* Added the core AI Assistant service layer with LLM provider abstractions, chat coordination, tool management, and use-case orchestration.
* Added image processing, encoding, and observability support with metrics tracking, file-based metrics reporting, and download progress feedback.

### Refactoring

* Refactored the add-on into layered packages for `config`, `context`, `core`, `image`, `observability`, `providers`, `service`, `tools`, `ui`, and `use_case`.
* Removed deprecated root-level modules and the legacy logger patching script.

### Fixes

* Fixed browser-aware page extraction by restoring safe NVDA context accessors for focus, focus ancestors, navigator, and foreground.

---

## v0.5.3 - 2026-04-12

### Refactoring

* Refactored AI assistant architecture to remove deprecated modules, introduce improved context management, and enhance LLM service integration.

### Improvements

* Added real-time provider title updates in the open chat window when switching between Ollama and Gemini.
* Implemented canonical chat message and tool handling for more reliable provider request payloads and tool invocation flow.
* Improved Gemini and Ollama tool-call serialization, provider state management, and debug logging.

---

## v0.5.2 - 2026-04-11

### Fixes

* Fixed Gemini streaming payload serialization by normalizing Gemini `contents` and `tools` request shapes.

### Improvements

* Improved Gemini streaming and debug logging to make request flow and tool-call behavior visible.
* Aligned Gemini chat and stream endpoints with the official API examples.

---

## v0.5.1 - 2026-04-11

### Refactoring

* Refactored add-on logging to use NVDA `logHandler` across core AI assistant modules.

### Improvements

* Improved tool-call and streaming diagnostics for more reliable assistant behavior.

---

## v0.5.0 - 2026-04-11

### Features

* Added a unified AI assistant command layer with a single main shortcut: `NVDA+Shift+A`.
* Added layer commands for summary, image description, chat, page-content chat, screenshot chat, and help.
* Added a new AI chat dialog with conversation history, tool calling support, and image/page context startup.

### Improvements

* Improved Ollama response extraction and image description prompt behavior for more reliable multimodal results.

### Refactoring

* Refactored provider handling, chat coordination, and request metrics reporting.

---

## v0.4.0 - 2026-04-10

### Refactoring

* Refactored the global plugin into focused modules for URL detection and bookmark management.

### Features

* Added on-demand current-page summarization through a local Ollama instance.

### Improvements

* Added bounded page text extraction and asynchronous summary delivery so NVDA remains responsive.
* Added user-facing documentation for the summary gesture and Ollama configuration.

---

## Notes

* This changelog follows a structured format with categorized entries: Features, Improvements, Fixes, and Refactoring.
* Future entries should be generated from Conventional Commits to ensure consistency and enable automation.
