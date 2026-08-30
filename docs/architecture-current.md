# Current architecture

This document describes the implementation in this repository as of August 2026. It is organized around runtime ownership and package boundaries; the protocol documents describe individual message schemas in more detail.

## 1. Runtime topology

~~~mermaid
flowchart LR
    NVDA[NVDA host process] --> PY[Python global plugin]
    PY --> UI[UIAdapter]
    UI -->|command pipe: newline JSON| HOST[nvda_ui_host.exe]
    HOST --> WEB[Svelte 5 Web UI]
    WEB -->|WebView messages| HOST
    HOST -->|event pipe: newline JSON| UI
    PY --> LLM[Provider backends]
    LLM --> EXT[PyO3 extensions]
    LLM --> LS[LiteRT / llama-server]
    PY --> STORE[(config, models, conversations)]
    EXT --> STORE
~~~

There are three processes at runtime:

1. NVDA, which loads the add-on and owns the accessibility object model.
2. The Python add-on, which owns application behavior, provider calls, configuration, context extraction, persistence, and presentation intent.
3. nvda_ui_host.exe, which owns the native window, WebView2 controller, WebView event loop, and Svelte rendering. It does not choose prompts, providers, or use cases.

Python and the host use two Windows named pipes:

- \\\\.\\pipe\\nvda_ai_assistant_ui_cmd: Python commands to the host and synchronous ack/error responses.
- \\\\.\\pipe\\nvda_ai_assistant_ui_evt: asynchronous UI events from the host back to Python.

Frames are UTF-8 JSON objects terminated by a newline. The v2 envelope contains schema, version, id, correlation_id, source, and type. Rust's source of truth is nvda_ui_host/src/protocol.rs; the Python mirror is addon/globalPlugins/AI-assistant/ui/host_protocol.py; names are generated from scripts/protocol.yaml.

## 2. Python add-on composition

### Entry point and application shell

- __init__.py bootstraps the package, puts bundled lib first on sys.path, and imports the global plugin.
- plugin/__init__.py initializes translations before importing plugin classes.
- plugin/controller.py defines GlobalPlugin, NVDA scripts, tray-menu integration, and gesture dispatch.
- plugin/application.py is the application facade. It composes services, maps gestures to use-case IDs, registers callbacks, starts optional local servers, and shuts everything down.
- plugin/layer_mode.py implements the temporary command layer activated by NVDA+Shift+A; digit selection is used for provider/model choice.
- plugin/background.py runs use cases, model preload, provider readiness, downloads, and local-server startup away from the NVDA main thread.
- plugin/presenter.py turns results, progress, errors, provider state, and result actions into view models and UI commands.
- plugin/factory.py is the composition root. It wires collectors, extractors, reducer, provider proxy, LLM service, chat coordinator, tools, metrics, and use-case engine.

The normal gesture path is:

~~~text
NVDA script -> GlobalPlugin -> AIAssistantApplication
  -> BackgroundTaskRunner -> UseCaseEngine
  -> ContextPipeline -> prompt/use case -> ProviderLLMService
  -> UseCasePresenter -> UIAdapter -> HostRenderer/native fallback
~~~

### Configuration and state

config/ is the persistence and normalization layer:

- defaults.py: default paths and values.
- settings.py: public settings API for active provider/model, endpoints, credentials, sampling, context limits, streaming, local-runtime settings, embeddings, and feature switches.
- model_config.py: per-model sampling overrides.
- provider_specs.py: provider-specific keys and fields.
- enabled_models.py: enabled model selections.
- state.py: in-process ProviderState snapshot and subscribers.
- yaml_store.py and store.py: YAML/JSON storage and protected secret handling.

The settings UI writes through this layer; provider and UI code should not edit configuration files directly.

### Core data and tools

core/ contains provider-neutral canonical objects:

- canonical.py: Message, Part, and canonical Tool.
- messages.py: LLM, summary, chat, and tool-result response models.
- message_transforms.py: conversion between canonical, provider, and UI representations.
- events.py: progress events and handlers.
- tooling.py: tool-call structures.

tools/ registers definitions, serializes tool declarations, executes provider tool calls, and returns canonical tool-result messages. The default composition registers get_time; the LLM service limits tool loops to five steps.

### Context collection and reduction

context/ is a two-phase pipeline designed around NVDA thread affinity.

1. ContextPipeline resolves page, focused-text, and image snapshots on the NVDA main thread.
2. Registered collectors consume snapshots and produce facts, text, metadata, and optional image data.
3. context/types.py carries typed snapshots, extraction results, prompt context, and extraction intents.
4. context/extractors/ selects browser-aware or generic extraction and parses page fields, selections, focused text, terminals, and editors.
5. context/formatting.py, structure_summary.py, and navigation.py turn NVDA/page structures into prompt-ready text and structural summaries.
6. context/reduction.py applies token budgets and optional semantic reduction/query retrieval through the embedding port.
7. context/request_registry.py validates resolver/collector ownership; graph_store.py persists accessibility graph captures.

The pipeline separates main-thread snapshot acquisition from thread-safe collection and prompt construction.

### Use cases and prompts

- use_case/engine.py validates and dispatches registered use cases, emits progress, presents normalized errors, and propagates result_actions.
- use_case/registry.py registers built-ins.
- summary.py, structure_summary.py, image.py, focus_image.py, proofread.py, and chat.py implement features.
- declarative.py supports spec-plus-prompt-builder use cases.
- base.py supplies shared collection, context-window budgeting, prompt validation, streaming callbacks, and Markdown conversion.
- prompts/ contains Jinja2-backed base, summary, image, and proofreading builders.

Most prompted use cases follow:

~~~text
ExtractionIntent -> ContextPipeline -> optional ContextReducer
  -> prompt builder -> LLMService -> typed UseCaseResult
~~~

### Providers and local runtimes

providers/interfaces.py defines the provider contract, errors, and model metadata. ProviderProxy is the active-provider facade; it observes provider state and delegates to a concrete provider.

- factory.py: constructs a provider from current configuration.
- adapters/openai_compat.py: OpenAI-compatible HTTP chat, streaming, image input, structured output, retries, and capabilities through llm_client.
- adapters/llama_cpp.py: llama-server specialization and advertised /models identity handling.
- litert_manager.py and llama_manager.py: installable model catalogs and model operations.
- registry.py: provider identity, lifecycle, capabilities, configuration fields, enablement, and model-manager selection.
- capabilities.py, policy.py, endpoints.py, and error_mapping.py: capability inspection, policy, endpoint normalization, and user-facing error suggestions.
- runtime/: downloads, paths, dynamic loading, model import, local-server supervision/readiness, and llama model catalog/preset reconciliation.

service/llm.py adds streaming policy, progress, canonical message conversion, and the bounded tool loop above the provider contract. service/provider_readiness.py, provider_catalog.py, provider_controls.py, and model_cache.py support presenter and settings/model dialogs.

### Chat, persistence, and observability

service/chat/ owns interactive sessions:

- ChatCoordinator builds user messages, applies page context, calls the LLM, streams progress, and commits turns.
- ConversationService exposes list/load/delete operations.
- ConversationRepository is the persistence port.
- repository_backends.py prefers the Rust memory_engine extension at %APPDATA%\\nvda\\AIAssistant\\conversations.db; it falls back to atomic JSON at conversations.json.
- projector.py maps canonical history to host transport messages.
- session.py, transaction.py, and types.py hold session and turn data.

observability/ records request context, events, and metrics. The file reporter is wired by plugin/factory.py.

### Image and embedding subsystems

image/ captures focused objects/windows/screenshots, checks screen-curtain state, preprocesses/resizes/encodes images, and exposes typed image services. CandleEmbeddingAdapter is a lazy port to the PyO3 embedding_engine; the reducer only loads it when embedding is enabled and required.

## 3. UI boundary and rendering

ui/adapter.py is the policy boundary. It owns a worker queue, host availability state, native fallback, session metadata, and translation of host events into application callbacks. It sends generic commands:

render_display, open_chat, sync_session, chat_set_history, chat_append, chat_update, chat_stream_begin/delta/end/abort, show_error, update_progress, and close_window.

The host path is split as follows:

- host_process.py: locates, starts, monitors, and stops the packaged EXE.
- host_transport.py: pywin32 named-pipe framing and event listener.
- host_protocol.py and host_protocol_constants.py: Python protocol model and generated names.
- host_renderer.py: payload construction, response handling, and event callback routing; it is not a business-state store.
- host_lifecycle.py: availability/readiness/recovery state.
- intent.py, view_models.py, session_state.py, and stream_projection.py: presentation intent, display/session models, provider-state projection, and stream-to-view updates.

Native NVDA gui/wx dialogs remain for settings, provider configuration, model management, downloads, and embedding-model preparation. The WebView is the primary result/chat surface when available; UIAdapter falls back when the EXE, pipes, or WebView are unavailable.

## 4. Rust host and Web UI

### Rust host modules

nvda_ui_host/src/main.rs initializes logging and COM, creates the native window, initializes WebView2, starts pipe listeners, and enters the Windows message loop.

- window.rs: HWND lifecycle, UI-thread dispatch, foreground/focus/hide, resize, and bounded queued commands.
- webview.rs: WebView2 initialization, embedded HTML loading, JS message reception, command posting, readiness, and event forwarding.
- host_dispatch.rs: command delivery and WebView state queueing.
- ipc/transport.rs: named-pipe servers, newline framing, command responses, event channel (capacity 256), disconnect handling, and requeueing.
- ipc/state.rs: event sender state shared by the event writer.
- protocol.rs: v2 envelope parsing, payload validation, typed commands, acknowledgements, errors, and host events.
- app.rs: command validation, activation policy, focus policy, and dispatch to WebView.
- logger.rs: host logging.

The host uses the windows crate for Win32/COM/windowing/pipes, webview2-com for WebView2, and serde/serde_json for protocol data.

### Svelte Web UI modules

webui/src/lib/bridge.ts is the inbound command entry point. It validates envelope/version, merges localized strings, extracts controls only for control commands, and dispatches through a command table.

- lib/commands/: pure handlers for open-chat, history, streaming, display, session synchronization, and error/progress/close.
- lib/operations/: control-state extraction and view lifecycle operations.
- state.svelte.ts: reactive app state; transcript.svelte.ts: transcript mutation/reactivity.
- protocol-types.ts: WebView-side mirror of Rust payload types.
- content.ts: sanitization/normalization; actions.ts: user actions; attachments.ts: attachments; shortcuts.ts: keyboard shortcuts.
- components/: chat, controls, messages, content blocks, attachments, result screens, status, toolbar, and accessibility announcements.

The Web UI sends chat_submitted, ui_action_invoked, provider/model selections, think-mode toggles, host close, and readiness events through window.chrome.webview.postMessage. Rust forwards them as host events; Python validates, persists, or reacts.

## 5. Native extensions and build dependencies

SCons invokes scripts/build.py, which builds and copies three PyO3 cdylib extensions into the add-on lib directory:

| Extension | Rust dependencies | Python owner/use |
| --- | --- | --- |
| llm_client | ureq, serde, serde_json, PyO3 | providers/adapters/openai_compat.py; HTTP and streaming |
| memory_engine | redb, serde, PyO3 | service/chat/repository_backends.py; conversation DB |
| embedding_engine | Candle, tokenizers, hf-hub, serde, dirs, PyO3 | embeddings/candle.py and manager.py |

Bundled pure-Python libraries include Jinja2, MarkupSafe, Markdown, Pygments, and latex2mathml. Runtime imports also rely on Pillow, PyYAML, and pywin32 in the NVDA/add-on environment. The build produces the UI host executable and embeds the Vite-built Svelte assets into the host.

## 6. Dependency graph

Arrows mean “imports or calls”; configuration and protocol edges are explicit.

~~~mermaid
flowchart TD
  plugin[plugin] --> usecase[use_case]
  plugin --> service[service]
  plugin --> ui[ui]
  plugin --> config[config]
  usecase --> context[context]
  usecase --> prompts[prompts]
  usecase --> service
  context --> image[image]
  context --> config
  context --> embeddings[embeddings]
  service --> providers[providers]
  service --> core[core]
  service --> tools[tools]
  service --> config
  providers --> core
  providers --> config
  providers --> native[PyO3 extensions]
  service --> observability[observability]
  ui --> config
  ui --> service
  ui --> protocol[host_protocol]
  ui --> nvda[NVDA APIs]
  plugin --> nvda
  context --> nvda
  image --> nvda
  protocol --> host[nvda_ui_host.exe]
  host --> webui[Svelte Web UI]
~~~

The intended dependency rule is that core types, context types, provider interfaces, and service ports remain provider/UI-neutral. NVDA and WebView2 details are concentrated at capture/UI edges and in the separate host process.

## 7. NVDA API inventory

NVDA-specific APIs are used at these boundaries:

- globalPluginHandler.GlobalPlugin: base class for the add-on entry point in plugin/controller.py.
- scriptHandler.script: declares keyboard scripts and gestures.
- addonHandler.initTranslation: initializes translations.
- gui, guiHelper, gui.settingsDialogs, and wx: tray menus, settings, provider/model dialogs, progress dialogs, and native fallback controls.
- api.getFocusObject, getNavigatorObject, getForegroundObject, getDesktopObject, and getFocusAncestors: focus/window/accessibility capture.
- textInfos.POSITION_ALL, POSITION_SELECTION, and POSITION_CARET: focused text, selection, caret, page ranges, and browser fields.
- treeInterceptorHandler: browser tree-interceptor resolution.
- controlTypes: browser/control-role and state interpretation.
- winUser and locationHelper.RectLTWH: Windows object geometry and capture coordinates.
- screenCurtain or legacy api.isScreenCurtainRunning: blocks screen capture under screen curtain.
- queueHandler.queueFunction(queueHandler.eventQueue, ...): marshals work to NVDA's event thread; ui.nvda_ui.call and queue wrap this.
- ui.message: user announcements; speech, speech.commands, and speech.extensions.pre_speechCanceled: controlled streaming announcements/cancellation.
- tones: optional progress/streaming tones.
- core.callLater: delayed post-result cleanup/focus handling.
- languageHandler: language/configuration integration.
- logHandler.log: NVDA logging throughout runtime, provider, capture, UI, and persistence error paths.
- api.getClipData: safe text clipboard extraction in utils/clipboard.py.

Worker threads may perform network, model, download, persistence, and prompt work, but NVDA object-model access and user announcements are marshalled through the NVDA event queue.

## 8. Representative interactions

### One-shot summary/image/proofreading

~~~text
gesture -> background worker -> use-case spec
  -> NVDA snapshot/context -> prompt -> provider request/stream
  -> progress + final result -> presenter -> UIAdapter
  -> render_display / stream commands -> WebView or native fallback
~~~

### Chat turn

~~~text
Web UI chat_submitted -> event pipe -> HostRenderer -> UIAdapter
  -> ChatCoordinator -> ConversationRepository load
  -> ProviderLLMService.generate_with_transcript
  -> optional ToolExecutor loop (max 5)
  -> streaming chat commands + persisted final turn
  -> Web UI transcript update
~~~

### Local model readiness

~~~text
provider selection/startup -> BackgroundTaskRunner
  -> ProviderReadiness/registry -> runtime supervisor
  -> adopt/start local server -> health + /models catalog
  -> provider adapter uses advertised model identity
~~~

### Result actions

Python serializes usable context/output items as generic actions. The Web UI emits ui_action_invoked; host_renderer.py forwards it; presenter.py maps it to adding context to current chat, opening a new chat, retrying, or navigating to a target. Provider and use-case semantics stay in Python.

## 9. Packaging and failure boundaries

SConstruct packages Python sources, bundled libraries, native extensions, the Rust host, and localized documentation. Host failure is isolated by UIAdapter and falls back to native NVDA UI. Missing optional extensions have narrower fallbacks: JSON conversations replace memory_engine, and context reduction can use deterministic behavior when embeddings are disabled/unavailable. Provider/runtime errors are converted by the service error-presentation layer before reaching users.

