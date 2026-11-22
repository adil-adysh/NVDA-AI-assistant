v0.15.0
========

Added
-----

* Press `NVDA+Shift+A`, then `O`, to get a page outline with headings, links,
  and interactive elements. This helps you understand a page before reading
  or asking follow-up questions in chat.
* Press `NVDA+Shift+A`, then `G`, to correct spelling and grammar in the
  focused edit box and review the suggested correction in the result window.
* Use external MCP tools in chat to ask AI Assistant to work with connected
  services, including NVDA through the NVDA MCP Bridge add-on and its separate
  companion MCP server. Install both, then add and connect the server under
  **NVDA menu → Tools → AI Assistant → Settings... → MCP Servers and Tools**.
  Review tool descriptions and input schemas, then approve tools individually
  or approve the server's read-only tools together. Enabled saved servers
  reconnect when NVDA starts.
* Set a maximum number of tool calls for each response to limit how many tool
  actions it can request.
* Copy a chat response as plain text or formatted Markdown with the copy
  buttons, or use `Alt+T` and `Alt+K` in the chat window.
* Download from a catalog of 21 community LiteRT-LM vision-language models,
  including LFM3-VL, MiniCPM-V, and Qwen3.5 Vision. The model manager shows
  download progress. When importing from Hugging Face, choose one exact
  `.litertlm` file; repositories with multiple files are supported when you
  specify the file to import.
* Create and edit llama.cpp Hugging Face presets, select an exact cached model
  file, add a speculative draft model, and set supported runtime options.
  Presets keep model sources portable without managing or deleting the shared
  Hugging Face cache.

Changed
-------

* Open provider and model management from **NVDA menu → Tools → AI Assistant
  → Settings... → Manage AI Providers...**. The same provider manager is also
  available directly from **Tools → AI Assistant → Manage AI Providers...**.
  Select a provider to enable or disable it, make it active, configure it, or
  manage its models. For model lists, combine the **Enabled state** and **Model
  status** filters to find available, not downloaded, downloading, or failed
  models. Text state labels and separate Enable and Disable buttons make the
  list easier to use with a screen reader.
* Choose whether LiteRT-LM and llama.cpp start on the first request or when
  NVDA starts. Only the active local provider starts with NVDA.
* Choose whether one-shot results are displayed, spoken, or both. Chat status
  announcements and automatic reading of completed answers have separate
  settings.
* Use think mode only with models that support it; the control is shown only
  for those models.
* Upgrade LiteRT-LM to version 0.19.1 from its startup notice or the
  **Upgrade LiteRT-LM Runtime** action in Manage AI Providers. If an older
  managed runtime could not be removed because it was in use, retry cleanup
  from the same manager.
* Hide the chat window with `Escape` while requests continue in the
  background. **Stop response** cancels generation and keeps the partial answer;
  drafts and attachments remain available when switching conversations.
* Ask a question about the current page directly in the chat input. AI
  Assistant retrieves relevant passages separately and keeps those excerpts
  out of the saved conversation.
* Download and select a local embedding model under **Manage Embedding
  Models** in Settings. Page chat uses downloaded model files for semantic
  matching.

Fixed
-----

* Keep chat input focus and the caret in place when a response finishes, and
  keep the window title and conversation content in sync when changing views.
* Remove internal thinking traces from spelling and grammar corrections.
* Show clear local-provider connection feedback and recover when a server is
  unavailable or its configuration changes.
* Keep provider and model list selection and screen-reader focus usable while
  filtering and refreshing.
* Preserve section headings when retrieving passages for page chat and
  prioritize exact matches for version numbers and error codes. Page chat
  falls back to keyword matching when embeddings are disabled or unavailable.
* Apply a changed llama-server executable the next time the managed server is
  started. Removing a preset stops an add-on-owned server, keeps model files
  and the shared Hugging Face cache, and leaves servers already running outside
  the add-on untouched.

v0.14.1
========

Fixed
-----

* MCP tool search and approval filter now have visible labels, so NVDA
  announces "Search tools:" and "Show:" instead of "Discovered tools:" and an
  unnamed combo box.

v0.14.0
========

Added
-----

* Added llama.cpp server integration through `llama-server` router mode.
* Added configurable llama-server executable, endpoint, and models preset path.
* Added API-backed llama model discovery using `/models` with `/v1/models` fallback.
* Added capability discovery for text, image, and audio modalities plus context-window metadata.
* Added MCP tool search, approval/read-only filters, a full details and input-schema preview, and one warning-led bulk approval for server-declared read-only tools.

Changed
-------

* llama-server model API responses are cached and treated as the runtime source of truth.
* Healthy llama-server routers now switch models without restarting the server.
* Existing llama presets preserve global defaults, comments, and per-model runtime options.

Fixed
-----

* Resolved llama model aliases between preset section IDs and Hugging Face source references.
* Added automatic llama-server startup when llama.cpp becomes the active provider.

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
