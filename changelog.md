v0.9.3
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
