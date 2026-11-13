# Current architecture

The llama manager now presents one configuration/external-model list. Add model
owns local/HF/cache source selection and optional vision, draft or MTP companion
descriptors. `models.json` remains authoritative; explicit companion options are
derived into runtime presets. Worker HF metadata lookup never downloads; remote
companion resolution occurs only for explicit Load or first inference. Cache
verification is role-aware, and shared-file deletion is blocked in both manager
and worker, including legacy projector/draft option paths.

`service/llama_operations.py` retains application-owned Load/Unload operations,
progress/error history and cancellation independently of dialog lifetime. Closing
the manager/Tasks detaches observers; Stop targets one operation. Disposable scans
still cancel on dismissal. Shutdown fences new operations before worker teardown.
Model unload is owned-server-only and succeeds only after observing unloaded.
Installed help gates option keys and speculative mode values; compatibility of
tensor/projector combinations is not inferred from filenames.

This document describes the implementation in this repository as of October 2026. It is organized around runtime ownership and package boundaries; the protocol documents describe individual message schemas in more detail.

Managed runtime calls use correlated `runtime_command` jobs. The command pipe
acknowledges submission and handles health, cancellation and shutdown promptly;
progress and terminal responses use the event pipe. LiteRT, llama, embeddings and
conversation persistence have separate serialized execution lanes. Status and
Stop have reserved execution capacity. Passive NVDA event-thread status reads
use cached snapshots and schedule asynchronous refresh; explicit authoritative
status reads must run off that thread. Command writes and reads have deadlines,
and a timed-out transaction reconnects before reuse. Job state is fenced by the
handshake generation and released when its consumer finishes. Progress congestion
may discard progress; terminal events are retained.

Managed-runtime preparation feedback is request-scoped. `core/readiness_progress.py` observes native lifecycle snapshots and emits startup, restart, and one delayed-preparation stage. Readiness RPCs opt in with `report_readiness_progress`; the worker sends `runtime_progress` frames with a `stage` of `starting`, `restarting`, or `delayed`, followed by the final response. `NamedPipeWorkerClient` waits for job events outside the command lock and translates stages in the NVDA process. No stages are sent to clients that do not opt in. Presentation checks cancellation, current chat identity, preparation lifetime, and output settings before speaking. Model loading is not inferred from elapsed time.

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

The application uses these process roles at runtime:

1. NVDA, which loads the add-on and owns the accessibility object model.
2. The Python add-on, which owns application behavior, provider calls, configuration, context extraction, persistence, and presentation intent.
3. nvda_ui_host.exe, which owns the native window, WebView2 controller, WebView event loop, and Svelte rendering. It does not choose prompts, providers, or use cases.
4. The private CPython worker, which runs local-runtime commands and jobs and hosts
   the native supervisor, embedding engine and conversation database. Its entry point is `worker/__main__.py`, launched with `python -B -m worker` from the add-on directory. Managed model servers run as its owned child processes.

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

Request cancellation is owned by Python through `core/cancellation.py`. Chat submissions carry request IDs; the coordinator saves stopped partial answers with `[Stopped]` and guards session generation. Background requests retain cancellation ownership through deferred speech and UI delivery. The generic `ui_action_invoked` event carries chat Stop, while NVDA's global Stop command covers summary/image requests. Escape only hides the host. Passive streaming commands preserve the hidden lifecycle; completed responses carry explicit activation and content focus intent. Native focus is correlated with the command acknowledgement and invalidated on dismissal.

service/chat/ owns interactive sessions:

- ChatCoordinator builds user messages, applies page context, calls the LLM, streams progress, and commits turns.
- ConversationService exposes list/load/delete operations.
- ConversationRepository is the persistence port.
- repository_worker.py is the NVDA-side repository port. In the worker, repository_backends.py prefers the Rust memory_engine extension at %APPDATA%\\nvda\\AIAssistant\\conversations.db; it falls back to atomic JSON at conversations.json.
- projector.py maps canonical history to host transport messages.
- session.py, transaction.py, and types.py hold session and turn data.

observability/ records request context, events, and metrics. The file reporter is wired by plugin/factory.py.

### Image and embedding subsystems

image/ captures focused objects/windows/screenshots, checks screen-curtain state, preprocesses/resizes/encodes images, and exposes typed image services. CandleEmbeddingAdapter is a lazy worker port to the PyO3 embedding_engine; the reducer only loads it when embedding is enabled and required.

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
  -> ProviderReadiness/registry -> lazy worker connection -> command pipe
  -> worker executor -> native Rust runtime supervisor
  -> adopt/start local server -> health + /models catalog
  -> provider adapter uses advertised model identity
~~~

### Result actions

Python serializes usable context/output items as generic actions. The Web UI emits ui_action_invoked; host_renderer.py forwards it; presenter.py maps it to adding context to current chat, opening a new chat, retrying, or navigating to a target. Provider and use-case semantics stay in Python.

## 9. Packaging and failure boundaries

The native process driver validates preset readability, INI line structure, and known incompatible preset options before spawning. It continuously drains server stderr into a bounded 64 KB buffer and attaches the final 4 KB to exit errors. Unknown options remain the installed server's responsibility; this avoids maintaining a second CLI implementation. Python preserves native diagnostics across readiness RPCs. Worker event-pipe loss completes pending jobs with a retryable `WORKER_DISCONNECTED` result, releases waiters, and invokes completion subscribers once. Worker failure speech is queued on the NVDA event thread on the first failure in a recovery episode. The llama model selector refreshes its local catalog without requiring server startup.

SConstruct packages Python sources, bundled libraries, native extensions, the Rust host, the isolated private CPython worker runtime, and localized documentation. By default the worker starts on the first model operation and model servers start on inference. Per-provider runtime settings can instead prepare the worker or start the local server at NVDA startup; only the active provider's choice applies. Application termination fences lazy launches and automatic recovery before asynchronous worker teardown. Host failure is isolated by UIAdapter and falls back to native NVDA UI. Missing optional extensions have narrower fallbacks: JSON conversations replace memory_engine, and context reduction can use deterministic behavior when embeddings are disabled/unavailable. Provider/runtime errors are converted by the service error-presentation layer before reaching users.


## Worker isolation and cancellation

Model discovery uses the central catalog cache, with generation fencing for fetch
results and deferred presenter callbacks. Endpoint, credential scope and catalog
configuration changes invalidate cached discoveries. Cloud model managers read
the central cache directly. Discovery failures remain retryable errors; capabilities
retain successful flags while refresh is loading or fails. Managed local discovery
is independent of inference readiness; authoritative LiteRT discovery prepares the
worker and reports unavailability rather than returning a successful empty list.

`core/llama_preset.py` owns pure preset reconciliation shared by NVDA and the worker.
Imports preserve quantization and explicit file selectors; unsupported non-main
llama.cpp revisions are rejected. Preset edits override stale manifest sources,
global context/reasoning settings contribute metadata, and relative model paths
resolve beside the preset before export. Preset replacement/removal is atomic.
Registering a remote reference does not imply its weights are already downloaded.

The worker advertises `job.runtime_command`, `job.embedding` and `job.conversation`.
The runtime dispatcher lives in `worker/runtime_commands.py` independently of pipe
transport. Current clients submit long operations as jobs; the legacy synchronous
runtime protocol remains for older clients. Worker jobs never import NVDA APIs.

Native embedding preparation/inference and database IO release the Python GIL.
Embedding requests are split into ordered batches of at most 256 texts, with
cancellation checks between native minibatches. Cancellation discards native
results; an individual native call may finish before yielding. LiteRT CLI jobs
poll cancellation, terminate their child and cap captured diagnostics. Native
startup checks cancellation immediately before launch and stops a late owned
startup when cancellation races with preparation. Adopted external servers are
never terminated by startup cancellation.

NVDA keeps gestures, screen-curtain checks, accessibility snapshots, prompts,
provider policy, chat state, speech and focus decisions. Chat open/switch/delete
and catalog presentation run on one serialized presentation IO lane. Worker
persistence commits are shielded from inference cancellation so stopped partial
answers remain saved. Image capture keeps object access on the NVDA event thread;
existing resize/encoding work runs on the calling background thread.

The packaged worker resolves native extensions through `../lib` in its private
Python path. Packaging tests run outside the checkout with PATH/PYTHONPATH cleared
and a temporary data directory; they exercise native imports, runtime status,
embedding validation, conversation IO and downloads.


### Deterministic llama.cpp model management

`ManagedModel` separates registration, source ownership, file availability,
runtime availability and explicit actions. llama.cpp remote registrations are
marked registered rather than downloaded. Missing local sources remain removable;
server-discovered rows are read-only registrations and never auto-import during
catalog lookup. The UI uses these actions instead of inferring removal from a
download state. Selection and mutations run on the background task boundary, with
refresh generations, completion speech and list focus restored after a mutation.

`LlamaPresetCodec` generates version-1 presets in canonical model-ID order.
`core/llama_options.py` owns supported options, aliases, validation and UI labels.
Per-model records hold explicit runtime options; imported `[*]` defaults are
flattened into those records. Preset import is a one-time migration, never a live
configuration link. Unsupported options are reported by section/key and block
import without changing the catalog or source file. The import summary lists the
models and settings migrated. Explicit reimport replaces matching IDs and retains
other registrations.

`models.json` is the authoritative catalog. Legacy list manifests and source-scoped
manifests migrate on first catalog access, preserving removed IDs. Once the manifest
has its authoritative marker, neither the original preset nor generated files are
read as model state. Original files remain unchanged, even when they are named
`models.ini` inside the managed directory. The derived output is `runtime-models.ini`.
Both NVDA and worker export from records rather than merging previous output.

Runtime settings load and save off the NVDA event thread. The accessible dialog
provides context, GPU layers, Flash Attention, cache precision/placement and MoE
expert placement/cache controls, with reset and validation. Mutually exclusive flags
are generated from a single placement choice. Other supported imported options
survive ordinary edits; Reset clears all runtime options. The worker inspects the
installed server's `--help`, with cancellation and a five-second deadline, and
caches supported flags by executable file identity. Unavailable controls are disabled;
unsupported configured flags fail before preset export and server launch. Provider
context defaults are applied only to unpinned models in the export, not as a router
command-line flag overriding per-model context. Changes take effect on the next
managed inference/load, with the existing startup fingerprint triggering a restart
when the derived preset changes.

The versioned model manifest retains exact removed IDs and retired server aliases.
Legacy list manifests are accepted. Catalog commits serialize across instances and
roll back manifest changes when an atomic preset export fails. Removal verifies
worker runtime status, stops only an owned router, and clears the active selection
using compare-and-set so it cannot clear a newer choice. It preserves original
model files and shared llama.cpp cache contents. Repeated removal is idempotent.

Cached-file deletion is a separate worker job. The worker resolves its own managed
cache root, requires an explicit add-on ownership record for the exact model/file,
and rejects caller-selected roots and paths outside that root. Current llama.cpp
Hugging Face downloads remain upstream-owned: importing a reference does not grant
this add-on permission to delete files from that shared cache.


### llama.cpp configuration, asset and server views

`providers/llama_catalog.py` is the shared presentation/selection policy. Entries
separate saved configurations, worker-verified downloaded assets and server models.
Runtime observations decode loaded/unloaded/loading/downloading/sleeping/failed
instead of treating discovery as proof that a model is loaded. Missing local sources
remain manageable but are excluded from ordinary selectors. Friendly names retain
stable inference IDs. Explicit model capabilities remain available before load;
a loaded server's actual capabilities take precedence.

`core/model_assets.py` provides immutable worker-safe snapshots. The model-asset
executor scans configured folders, worker-visible llama.cpp and HF Hub caches with
cancellation and limits. It checks GGUF headers, treats shard/projector entries as
unsupported for standalone creation, deduplicates resolved paths and rejects links
outside the declared root. It does not load weights or claim full tensor integrity.
Opaque tokens expire and file identity is rechecked before reuse. Verified HF source
metadata is retained in configuration records; cache ownership stays with the user.

`ui/llama_model_manager.py` provides one accessible manager with three views, named
columns, explicit primary actions, search, visibility controls and source details.
Read tasks do not invalidate catalogs or move focus; durable mutations refresh the
catalog with generation fences. Stop requests are distinct from errors, and closed
views reject late results. `ui/llama_configuration_dialog.py` collects friendly name,
source and optional stable ID. Cached creation references existing files without
copying, downloading or starting an inference server. Several configurations can
share one asset. Existing verified add-on-owned deletion is separate from removal.

Preset imports have a preview, explicit replacement IDs, and source/catalog digests
rechecked at commit. Runtime settings use Basic/Advanced pages with stored/effective
values, default origins and individually removable unsupported options. Runtime
allocation is separate from request context budgeting. Explicit preparation uses
an owned router load request and waits for authoritative loaded status. Cancellation
requests unload of that model, fenced against replacement server generations; it
does not terminate an external server. Settings and gestures consume the shared
selectable model policy through the manager/provider catalog.
