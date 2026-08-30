---
applyTo: "addon/globalPlugins/AI-assistant/**/*.py"
description: "Use when editing the NVDA add-on Python code, including plugin, use cases, context, services, providers, tools, and UI adapter layers."
---

# Python Add-on Instructions

Use the existing layered architecture before adding new abstractions.

## Routing

- `plugin/` handles NVDA gestures, lifecycle, and background scheduling only.
- `use_case/` orchestrates a feature and should stay free of provider-specific or NVDA API logic.
- `context/` collects structured context through the `ContextPipeline` which uses `ExtractionIntent` (carrying typed `ContentRequest` objects) and resolves snapshots in two phases: Phase 1 (NVDA main thread) for extraction and image capture, Phase 2 (thread-safe) for collector dispatch via `CollectorInput`. New collectors implement the `ContextCollector` protocol with `handles_request()` and `collect_for_request()`.
- `service/` owns chat coordination, tool execution, and provider-facing workflows.
- `providers/` contains provider-specific behavior behind shared protocols and proxy layers.
- `ui/` adapts results into UI intents, host protocol messages, and native
  NVDA fallback; `nvda_ui_host/` is the separate Rust/WebView2 project.

## Implementation Rules

- Prefer extending an existing `UseCase`, presenter, context collector, or service before creating a new top-level concept.
- Register new use cases in `use_case/registry.py` and route them through `UseCaseEngine`.
- Keep prompt context typed and structured. Do not manually concatenate large prompt strings in arbitrary layers.
- Express what a use case needs from the context as an `ExtractionIntent` containing explicit `ContentRequest` typed requests rather than building ad-hoc context or passing raw prompts.
- Use the provider proxy and service layer rather than calling Gemini, Ollama, or OpenAI clients from feature code.
- Keep long-running work off the NVDA main thread and preserve graceful failure behavior.
- Use `ui/nvda_ui.py` and the `ContextPipeline` main-thread boundary for NVDA
  object-model access, focus/page extraction, and announcements. Do not pass
  live NVDA objects into provider, service, or worker-thread code.
- Treat `llm_client`, `memory_engine`, and `embedding_engine` as optional
  PyO3 runtime boundaries and preserve their documented fallbacks.
- Follow the repository typing posture: strict type hints, explicit data shapes, and minimal dynamic behavior.
- For host-backed UI work, prefer `ui/intent.py` and presenter/view-model metadata over browser-layer heuristics.
- Keep `ui/adapter.py` focused on coordination. Extract stream projection or payload shaping into helpers when it starts owning too many details.
- Translator-facing WebView labels and status strings should originate in Python metadata rather than being invented in the Web UI.
- Strings that must appear in the generated POT file should live in Python source scanned by `i18nSources` and use a gettext extraction keyword recognized by the repo's `xgettext` configuration, such as `translate(...)`.
- Add `# TRANSLATORS:` comments immediately above extracted msgids when the UI meaning would not be obvious from the text alone.

## Validation

- Run `uv sync --locked` after dependency or lockfile changes.
- Start with `uv run ruff check .` and focused `uv run pytest` nodes for Python
  edits. Use `uv run pytest` for shared test/bootstrap changes.
- Put tests only in top-level `tests/` and load add-on modules through
  `tests/support/bootstrap.py`. Do not create tests, fixtures, or pytest config
  in `addon/`.
- Use real API definitions from the sibling NVDA checkout pinned by
  `nvda-source.toml`; keep fakes narrow and limited to live-process services.
- Do not weaken packaging exclusions: `.nvda-addon` archives may not contain
  tests, pytest artifacts, fixtures, or bytecode.
- Use targeted runtime checks or Pyright validation when the change affects types, protocols, or import wiring.
- When editing UI host adapters or protocol models in Python, validate the corresponding Rust or Web UI side too.
