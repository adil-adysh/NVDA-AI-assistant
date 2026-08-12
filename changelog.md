v0.13.0
Added
• 
LiteRT-LM local inference provider — a fully self-contained local runtime that is downloaded on demand (no separate Python or Ollama install required), with one-click model download from Hugging Face
• 
Unified OpenAI-compatible provider adapter — a single adapter now serves Ollama, OpenAI, Gemini, LiteRT-LM, and any other server that speaks the /v1/chat/completions protocol
• 
Manage AI Providers dialog — enable or disable providers, install the LiteRT-LM runtime, set the active provider, and manage models from one place
• 
Per-model sampling configuration — context window, temperature, top-k, top-p, max tokens, and repetition penalty can now be pinned per model, with a "use default" fallback and a reset option
• 
Global model defaults for context window, temperature, top-p, and max tokens
• 
Digit-based provider and model selection in the assistant layer — press T or M, then a number, to switch instantly
• 
Human-readable model labels in the chat model selector
• 
"Add to chat" and "Open in new chat" actions for one-shot results such as summaries and image descriptions
• 
LiteRT-LM model download and deletion with a progress dialog and automatic HTTP retry
• 
Centralized model catalog cache with background preloading, so model lists load without blocking the interface
• 
Soft-dismiss chat window — pressing Escape hides the window while streaming continues in the background; it reappears automatically when the response is ready
• 
LiteRT-LM backend selection (CPU, GPU, NPU) and context window configuration, with automatic server restart when engine settings change
• 
Keyboard navigation, accessible field labels, and unique checkbox labels across configuration dialogs
Changed
• 
Adopted friendly model names as the universal identity across configuration, server, and UI
• 
LiteRT-LM server now starts automatically with the add-on
• 
Provider configuration rebuilt around a registry with per-model sampling and provider enable/disable
Improved
• 
Model lists load faster and no longer block the interface, thanks to background preloading and caching
• 
Provider and model switching in the assistant layer now uses numbered choices
Fixed
• 
WebView focus deferred until after the UI re-renders, preventing NVDA from reading the pane role on programmatic activation
• 
Focus capture moved to the main thread and tool call IDs propagated correctly
• 
Deleted source models now stay visible in the model list
• 
Console window suppressed when running the LiteRT-LM CLI
Developer Notes
• 
Added native PyO3 LLM client extension with a Rust OpenAI-compatible client used by providers
• 
Added embedding engine PyO3 extension with Candle-based MiniLM and Granite/Harrier embedding models, benchmarks, and validation tests
• 
Added a CI workflow for building and releasing LiteRT-LM runtime bundles
v0.10.0
Added
• 
API key encryption at rest via Windows DPAPI — Gemini and OpenAI keys are now encrypted in config.yaml instead of stored as plaintext (existing keys migrated automatically on save)
• 
Add to current chat action for attaching chat without a token roundtrip
Changed
• 
WebView UI migrated from JavaScript to TypeScript with Svelte 5 clean architecture — improved reliability, modular command handling, elimination of fragile reactivity patterns, and better debugging visibility
• 
Protocol layer unified under a single canonical YAML spec — all commands and events now defined in one place across Python, Rust, and TypeScript, reducing cross-layer inconsistencies
• 
Consolidated logging in the host application dispatch path for cleaner debug output
Improved
• 
Streaming and state management performance through simplified reactivity chain and centralized control-state extraction
• 
Code quality across provider layer — shared HTTP utilities extracted from Ollama and OpenAI clients, removing ~130 lines of duplicated logic
• 
Session type separation — TypedDict definitions extracted from session state module for clearer imports
• 
Stream projection logic extracted to dedicated module for better testability
• 
Model cache extracted from main presenter for simpler threading and provider refresh logic
Fixed
• 
Legacy EVENT_HOST_CLOSED naming aligned with canonical close_host spec across all layers
Developer Notes
• 
Added behavioral specification docs for protocol contract, stream projection lifecycle, and presentation intent metadata
• 
Introduced canonical protocol code generator — adding a new command/event now means editing one YAML file and regenerating
v0.8.0
Added
• 
Embedded WebView-based UI host for modernized interaction handling
• 
Real-time streaming chat responses
• 
Image upload and attachment support
• 
Dynamic provider/model selection
• 
Foundational memory engine infrastructure
• 
Session synchronization support
• 
Expanded accessibility and keyboard navigation support
Changed
• 
Refactored IPC communication architecture for improved reliability
• 
Improved window activation and focus behavior
• 
Updated chat rendering pipeline for smoother streaming updates
• 
Enhanced attachment validation and rendering logic
• 
Modernized frontend state management and UI composition
Improved
• 
Faster and more responsive UI updates
• 
Better screen reader compatibility
• 
Improved logging and debugging infrastructure
• 
Cleaner protocol separation between commands and events
• 
More maintainable provider and runtime abstractions
Fixed
• 
Model normalization inconsistencies
• 
Multiple window-close edge cases
• 
Streaming synchronization issues
• 
Various focus and state-management bugs
Developer Notes
• 
Added architecture and protocol documentation
• 
Expanded unit test coverage
• 
Introduced extensible host transport abstractions
• 
Improved command queue and activation policy handling
