# Audit Report: Model Management Consolidation & Multi-Modal Architecture
**Role:** Model-Management Architect (Agent 5)  
**Repository:** `adil-adysh/NVDA-AI-assistant`  
**HEAD Commit:** `ced1cbc`  
**Deliverable Targets:** Audit F (Model Management Consolidation) & Invariants A11–A15 (Central `ModelManagementService` across Multi-Modalities)  
**Date:** 2026-10-02  

---

## 1. Executive Summary

This audit performs an evidence-driven code inspection of the model management, catalog caching, download orchestration, readiness evaluation, and persistence mechanisms across the repository at commit `ced1cbc`. 

### Key Findings Summary:
1. **State Fragmentation & Redundancy:** Model state and availability are fractured across six disjoint, non-interoperable enums and representations (`CatalogState` in `service/model_cache.py`, `ModelState` in `providers/model_manager.py`, `ConfiguredModelState` and `ProviderReadinessState` in `service/provider_readiness.py`, `ProviderModelInfo` in `providers/interfaces.py`, `EmbeddingModelInfo` in `embeddings/manager.py`, and `LlamaModelRecord` in `providers/runtime/llama_models.py`).
2. **Blocking Network Sockets on Main/UI Threads:** `ProviderReadinessService.evaluate()` performs synchronous HTTP requests (`/health` and `/v1/models`) when checking `llama-cpp-server` (lines 219, 340-344 in `service/provider_readiness.py`), directly endangering the responsiveness of NVDA's event loop and gestures.
3. **Silent Configuration Mutations & Dangerous Fallbacks:** When starting `llama-server`, if the configured model is absent, `plugin/background.py` (lines 183-196) silently mutates user configuration by picking an arbitrary model from the preset and calling `set_model_name()`, violating architectural transparency. Similarly, `service/provider_readiness.py` (lines 196-210) reports LiteRT as `READY` when its catalog is `COLD`, silently bypassing download verification.
4. **Isolated Modality Silos:** The repository has no unified multi-modal model management layer. Embeddings are sequestered in an isolated native Candle subsystem (`embeddings/manager.py`), Vision is merely a boolean capability flag on LLMs, and OCR, Transcription, and TTS have no model infrastructure, resource arbitration, or concurrency control. Running multiple local models concurrently currently risks memory exhaustion and GPU thrashing.
5. **Duplicated Negative Visibility Filtering:** `ModelVisibilityStore` is queried ad-hoc in five different modules (`service/provider_controls.py`, `service/provider_readiness.py`, `ui/settings_panel.py`, `ui/session_state.py`, and `ui/model_manager.py`), with UI layers re-injecting hidden models when they are active.

To resolve these deficiencies and enforce Invariants A11–A15, this report specifies the design of a centralized application `ModelManagementService` coordinating smaller collaborators across all six modalities (**CHAT**, **VISION**, **OCR**, **TRANSCRIPTION**, **EMBEDDING**, **TTS**).

---

## 2. Current Model Management Architecture & Responsibility Map (Audit F)

Below is the concrete code mapping of every file participating in model management at HEAD (`ced1cbc`).

### 2.1 File-by-File Breakdown & Symbol Citations

#### 1. `addon/globalPlugins/AI-assistant/service/model_cache.py` (451 lines)
- **Role:** Centralized model catalog cache and capability cache for chat/LLM providers.
- **Key Symbols & Locations:**
  - `CatalogState` enum (`COLD`, `LOADING`, `READY`, `EMPTY`, `ERROR` at lines 35–40).
  - `ModelCatalogSnapshot` dataclass (`provider_id`, `state`, `models: tuple[ProviderModelInfo, ...]`, `error_message`, `version` at lines 43–52).
  - `_FetchGate` synchronization primitive (`threading.Event`, `result`, `error` at lines 54–68).
  - `ModelCatalogCache` class (lines 70–387):
    - `get_models(provider_id)`: Synchronous blocking fetch if cold/error (lines 99–121).
    - `get_models_or_empty(provider_id)`: Non-blocking reader for NVDA thread (lines 123–134).
    - `get_snapshot(provider_id)`: Non-blocking snapshot reader (lines 135–150).
    - `preload_all()`: Spawns unmanaged daemon thread `ModelCatalogPreload` (lines 188–195).
    - `preload_async(provider_id)`: Spawns unmanaged daemon thread `ModelCatalogFetch-{provider_id}` (lines 197–219).
    - `_perform_fetch(provider_id)`: Calls `self._get_catalog().list_models(config)` (lines 293–306).
  - `ModelCapabilityCache` class (lines 388–446):
    - Keys on `(provider_id, model_id)`; calls synchronous `get_models()` if snapshot is `COLD` or `ERROR` (line 411).
  - Global singletons: `model_catalog_cache` and `model_capability_cache` (lines 449–450).

#### 2. `addon/globalPlugins/AI-assistant/plugin/model_cache.py` (41 lines)
- **Role:** Deprecated backwards-compatibility wrapper.
- **Key Symbols & Locations:**
  - `ModelCache` class (lines 13–41): wraps `model_catalog_cache` subscriptions and transforms snapshots to tuple of IDs.

#### 3. `addon/globalPlugins/AI-assistant/service/provider_catalog.py` (40 lines)
- **Role:** Discovery bridge between `ProviderConfig` and `LLMProvider.list_models()`.
- **Key Symbols & Locations:**
  - `ProviderCatalogService.list_models(config)` (lines 30–39):
    - Evaluates readiness via `_readiness_service.evaluate(config)` (line 31).
    - If `not readiness.can_list_models`, returns `()` (lines 32–33).
    - Instantiates a throwaway provider instance: `provider = self._provider_factory(config)` (line 35).
    - Calls `provider.list_models()` and immediately closes it in `finally: provider.close()` (lines 37–39).

#### 4. `addon/globalPlugins/AI-assistant/service/provider_controls.py` (231 lines)
- **Role:** High-level provider and model switching coordinator for gestures and UI.
- **Key Symbols & Locations:**
  - `ProviderControlResult` & `ModelSwitchResult` dataclasses (lines 27–43).
  - `ProviderControlService` class (lines 45–230):
    - `list_models(provider_id)`: Delegates to `_model_cache.get_models(provider_id)` (blocking network call) (lines 89–96).
    - `list_models_cached(provider_id)`: Calls non-blocking `get_models_or_empty()` (lines 98–103).
    - `refresh_models(provider_id)`: Invalidates cache and calls blocking `get_models()` (lines 105–114).
    - `list_enabled_models(provider_id)`: Calls blocking `list_models()`, then filters via `_enabled_store.is_model_visible()` (lines 116–133).
    - `select_model(model, provider)`: Updates config and saves (lines 183–208).

#### 5. `addon/globalPlugins/AI-assistant/service/provider_readiness.py` (345 lines)
- **Role:** Runtime readiness and configured model validity evaluator.
- **Key Symbols & Locations:**
  - `ModelCatalogAuthority` enum (`AUTHORITATIVE`, `ADVISORY`, `NONE` at lines 13–19).
  - `ConfiguredModelState` enum (`VALID`, `NOT_CONFIGURED`, `UNAVAILABLE`, `DISABLED`, `UNKNOWN` at lines 21–29).
  - `ConfiguredModelStatus` dataclass (lines 31–38).
  - `ProviderReadinessState` & `ProviderReadinessReason` enums (lines 40–57).
  - `ProviderReadiness` dataclass (`can_infer`, `can_list_models`, `model_status` at lines 76–93).
  - `ProviderReadinessService.evaluate(config)` (lines 98–292):
    - Queries `ModelVisibilityStore` to check `is_model_visible` (lines 135–156).
    - For LiteRT (`policy.requires_runtime`): Checks `model_catalog_cache.get_snapshot("litert-lm")`. If snapshot is `READY` or `EMPTY`, checks model membership; if snapshot is `COLD`, silently skips check and returns `READY` (lines 172–210).
    - For `llama-cpp-server`: Creates `LlamaCppModelManager(config=config)` and calls `manager.list_server_models()` (HTTP GET to server) if record is missing (lines 217–224). Calls `self._llama_server_is_ready(config, record)` which probes `/health` and `/v1/models` over HTTP (lines 241, 323–345).

#### 6. `addon/globalPlugins/AI-assistant/providers/model_manager.py` (285 lines)
- **Role:** Shared contract and cloud adapter for model manager dialogs.
- **Key Symbols & Locations:**
  - `ModelState` enum (`READY`, `DOWNLOADED`, `NOT_DOWNLOADED`, `DOWNLOADING`, `FAILED` at lines 27–43).
  - `ManagedModel` dataclass (`id`, `display_name`, `state`, `priority`, `size_hint`, `capabilities`, `description`, `canonical_id` at lines 45–61).
  - `ProviderFeatures` dataclass (`download`, `delete`, `import_model` at lines 63–73).
  - `ModelManagerProvider` protocol (lines 76–149).
  - `CloudModelManagerAdapter` (lines 151–285): Wraps cloud providers, maintains separate `_cached_models` list protected by `_cache_lock`, checks `model_cache` first, then falls back to `_provider_class(config).list_models()`.

#### 7. `addon/globalPlugins/AI-assistant/providers/litert_manager.py` (382 lines) & `litert_models.py` (623 lines)
- **Role:** Local LiteRT-LM model manager, static model definitions, and download coordinator.
- **Key Symbols & Locations:**
  - `LiteRTModelDef` and `ModelVariant` dataclasses (`litert_models.py` lines 16–144).
  - `has_gpu()` hardware probe via `ctypes` (`litert_models.py` lines 531–566).
  - `LiteRTModelManager` class (`litert_manager.py` lines 40–382):
    - `list_managed_models()`: Combines `recommended_models()`, `supervisor.list_server_models()`, and filesystem check `svc.is_downloaded(filename)` (lines 74–150).
    - `download_model(model_id)`: Calls `ModelDownloadService().download()`, then auto-imports via `supervisor.import_model()`, then invalidates `model_catalog_cache` and `model_capability_cache` (lines 156–206).
    - `import_model(request)`: Staged import for local file or Hugging Face repo (lines 207–269).
    - `delete_model(model_id)`: Unregisters from server and unlinks cache files (lines 274–309).
    - `set_active_model(model_id)`: Imports if needed, then persists `set_litert_model_name()` (lines 314–354).

#### 8. `addon/globalPlugins/AI-assistant/providers/llama_manager.py` (284 lines) & `runtime/llama_models.py` (364 lines)
- **Role:** Local llama.cpp model manager, catalog persistence, and router preset builder.
- **Key Symbols & Locations:**
  - `LlamaModelRecord` dataclass (`llama_models.py` lines 18–60).
  - `LlamaModelCatalog` (`llama_models.py` lines 235–364): Persists `%APPDATA%/nvda/AIAssistant/models/llama-cpp/models.json` and `models.ini`.
  - `LlamaCppModelManager` class (`llama_manager.py` lines 33–284):
    - `list_managed_models()`: Synthesizes disk records and `supervisor.list_models()` (lines 81–110).
    - `download_model(model_id)`: Calls `ensure_running(record)` (lines 152–165).
    - `ensure_running(record)`: Writes preset via `_catalog.write_preset()`, stops/adopts/starts `llama-server` process (lines 166–226).
    - `import_model(request)`: Upserts record to `LlamaModelCatalog` (lines 115–151).

#### 9. `addon/globalPlugins/AI-assistant/providers/runtime/model_download.py` (268 lines) & `download.py` (444 lines)
- **Role:** File streaming, range resume, and HF tree inspector.
- **Key Symbols & Locations:**
  - `ModelDownloadService` (`model_download.py` lines 35–235):
    - Default cache directory: `%APPDATA%/nvda/AIAssistant/models/litert-lm/` (lines 240–245).
    - `download()`: Uses `.part` file, calls `_download_url_resume()`, optional SHA-256 (lines 64–152).
    - `download_huggingface()`: Queries Hugging Face tree API over HTTP (lines 154–214).
    - `stage_local_file()`: Copies file to cache dir (lines 215–227).
  - `RuntimeDownloadService` (`download.py` lines 47–150): Downloads backend ZIP bundles to versioned paths.

#### 10. `addon/globalPlugins/AI-assistant/embeddings/manager.py` (106 lines)
- **Role:** Isolated local embedding model service.
- **Key Symbols & Locations:**
  - `EmbeddingModelInfo` dataclass (lines 11–19).
  - `embedding_cache_dir()`: `%APPDATA%/nvda/AIAssistant/models/embeddings` (lines 21–26).
  - `EmbeddingModelService` (lines 29–105):
    - Calls native `embedding_engine.EmbeddingEngine` (Rust/Candle).
    - `prepare(model_id)`: Triggers native download and caching (lines 57–70).
    - `is_cached(model_id)`: Inspects native cache (lines 71–79).
    - `delete(model_id)`: Deletes cached model (lines 80–87).

#### 11. `addon/globalPlugins/AI-assistant/config/enabled_models.py` (209 lines)
- **Role:** Negative visibility storage.
- **Key Symbols & Locations:**
  - `ModelVisibilityStore` (aliased as `EnabledModelsStore`):
    - File: `%APPDATA%/nvda/AIAssistant/model_visibility.json` (lines 22–26).
    - Inverted storage pattern: tracks explicitly *disabled* models per provider. New models are visible by default.
    - Methods: `is_model_visible()`, `set_model_visible()`, `get_disabled_models()`, `get_visible_models()` (lines 51–109).

#### 12. `addon/globalPlugins/AI-assistant/config/model_config.py` (416 lines)
- **Role:** Per-model sampling parameter persistence.
- **Key Symbols & Locations:**
  - `ModelConfigStore`: Persists `%APPDATA%/nvda/AIAssistant/model_configs.json` for `(provider_id, model_id)`.
  - Pinned fields: `num_ctx`, `temperature`, `top_k`, `top_p`, `max_tokens`, `repeat_penalty`, `thinking` (lines 59–85).

#### 13. `addon/globalPlugins/AI-assistant/ui/model_manager.py` (786 lines) & `ui/embedding_model_dialog.py` (197 lines)
- **Role:** Native Wx dialogs for model browsing, downloads, and visibility toggling.
- **Key Symbols & Locations:**
  - `ModelManagerDialog` (`ui/model_manager.py` lines 47–785):
    - Wx ListCtrl with checkboxes (col 0), active indicator (col 1), display name (col 2), status (col 3), size (col 4).
    - `_pending_downloads: set[str]` tracking (line 66).
    - Spawns `DownloadProgressDialog.run(worker=...)` on worker thread (lines 506–535).
    - On complete, invalidates `model_catalog_cache` and `model_capability_cache` (lines 524–525).
  - `EmbeddingModelManagementDialog` (`ui/embedding_model_dialog.py` lines 19–196):
    - Completely separate dialog for embedding models; maintains `_cached: dict[str, bool]`.

#### 14. `addon/globalPlugins/AI-assistant/ui/settings_panel.py` (479 lines)
- **Role:** General settings panel.
- **Key Symbols & Locations:**
  - `AIAssistantGeneralPanel._model_choices_for(provider_id)` (lines 164–185):
    - Attempts `build_model_manager(provider_id).list_managed_models()`.
    - Fallback: `model_catalog_cache.get_models_or_empty(provider_id)`.
    - Filters by `ModelVisibilityStore().is_model_visible(provider_id, m)`.
    - If active model not in choices, prepends it anyway (lines 182–184).

#### 15. `addon/globalPlugins/AI-assistant/plugin/background.py` (495 lines) & `plugin/local_provider_startup.py` (50 lines)
- **Role:** Background task runner, provider startup, and model preloading.
- **Key Symbols & Locations:**
  - `ensure_provider_server_ready()` (`background.py` lines 163–203):
    - For `llama-cpp-server`: If model not found, silently picks `available_records[0]`, sets model via `set_model_name()`, and starts it (lines 183–196).
  - `start_model_preload()` (`background.py` lines 404–440):
    - Spawns raw thread `BrowserAssistantModelPreload`, evaluates readiness, speaks to NVDA, calls `llm_service.ensure_model_available()`.
  - `schedule_active_local_provider_start()` (`local_provider_startup.py` lines 13–50):
    - Spawns daemon thread `{provider}ServerAutoStart` during startup.

#### 16. `plugin/presenter.py`, `ui/session_state.py`, and `nvda_ui_host/webui`
- **Role:** Session state propagation to WebView host.
- **Key Symbols & Locations:**
  - `presenter.py`: `_get_cached_models()` reads `model_catalog_cache.get_models_or_empty()`, listens to `model_catalog_cache.subscribe()` (lines 355–390).
  - `session_state.py`: `_filter_available_models()` queries `ModelVisibilityStore` (lines 382–390); `_resolve_model_labels()` calls `build_model_manager(provider).list_managed_models()` (lines 398–429).
  - Web UI `ControlPanel.svelte`: Renders `availableModels` select box (lines 108–130).

---

## 3. Classified Audit Findings

Every finding is classified using the mandatory tags: `CONFIRMED`, `LIKELY`, `DESIGN DETAIL`, `BLOCKER`, or `UNKNOWN / REQUIRES EXPERIMENT`.

### Finding F1 [CONFIRMED, BLOCKER]: Fragmented Model State Representations
- **Location:**
  - `addon/globalPlugins/AI-assistant/service/model_cache.py:35–52` (`CatalogState`, `ModelCatalogSnapshot`)
  - `addon/globalPlugins/AI-assistant/providers/model_manager.py:27–61` (`ModelState`, `ManagedModel`)
  - `addon/globalPlugins/AI-assistant/service/provider_readiness.py:21–38` (`ConfiguredModelState`, `ConfiguredModelStatus`)
  - `addon/globalPlugins/AI-assistant/providers/interfaces.py:80–93` (`ProviderModelInfo`)
  - `addon/globalPlugins/AI-assistant/embeddings/manager.py:11–19` (`EmbeddingModelInfo`)
  - `addon/globalPlugins/AI-assistant/providers/runtime/llama_models.py:18–60` (`LlamaModelRecord`)
- **Evidence:**
  Six distinct, non-interoperable structures represent "a model". `CatalogState` measures provider discovery (`COLD`, `LOADING`, `READY`, `EMPTY`, `ERROR`), `ModelState` measures local disk readiness (`READY`, `DOWNLOADED`, `NOT_DOWNLOADED`, `DOWNLOADING`, `FAILED`), and `ConfiguredModelState` measures user configuration status (`VALID`, `NOT_CONFIGURED`, `UNAVAILABLE`, `DISABLED`, `UNKNOWN`). None share common identity fields or capability abstractions.
- **Impact:**
  Translating across these boundaries requires repetitive conversions (e.g. `_convert_to_managed()` in `providers/model_manager.py:230-254`, `_resolve_model_labels()` in `ui/session_state.py:423-428`). It is impossible to plug in non-LLM models (Vision, OCR, Transcription, Embedding, TTS) without creating yet another parallel stack.

### Finding F2 [CONFIRMED, BLOCKER]: Synchronous HTTP Sockets in Readiness Evaluation
- **Location:**
  - `addon/globalPlugins/AI-assistant/service/provider_readiness.py:217–224, 337–344`
- **Evidence:**
  Inside `ProviderReadinessService.evaluate()`:
  ```python
  217: manager = LlamaCppModelManager(config=config)
  218: record = manager.find_record(model_name)
  219: server_items = manager.list_server_models() if record is None else ()
  ...
  241: if not self._llama_server_is_ready(config, record):
  ...
  337: supervisor = get_llama_supervisor(executable, host, port)
  340: if not supervisor.is_healthy():  # Sends HTTP GET to /health
  344: return any(record.matches_server_id(str(item.get("id", ""))) for item in supervisor.list_models()) # Sends HTTP GET to /v1/models
  ```
- **Impact:**
  `evaluate()` is called directly on the NVDA main thread from gestures (`ProviderControlService.current_state()`), UI initializers, and dialog builders. If `llama-server` is starting, stalled, or encountering a TCP timeout, the NVDA speech engine and UI thread freeze.

### Finding F3 [CONFIRMED, BLOCKER]: Silent Configuration Mutation & Model Fallback
- **Location:**
  - `addon/globalPlugins/AI-assistant/plugin/background.py:183–196`
- **Evidence:**
  ```python
  182: model_name = str(config.model_name or "").strip()
  183: record = manager.find_record(model_name) if model_name else None
  184: if record is None:
  185:     available_records = manager._catalog.list_records()
  186:     if available_records:
  187:         record = available_records[0]
  188:         log.info("Configured llama.cpp model %r not found; starting server with %r...", model_name, record.model_id)
  192:         try:
  193:             from ..config.settings import set_model_name
  194:             set_model_name(record.model_id)
  195:         except Exception:
  196:             pass
  ```
- **Impact:**
  Violates Invariant A14 (Zero Silent Fallbacks). If a user configures a specific model and it is unavailable, the background worker silently overwrites their persisted configuration to a different model without user consent or notification.

### Finding F4 [CONFIRMED, BLOCKER]: False-Positive Readiness on Cold Cache
- **Location:**
  - `addon/globalPlugins/AI-assistant/service/provider_readiness.py:172–210`
- **Evidence:**
  For LiteRT-LM, `evaluate()` checks `model_catalog_cache.get_snapshot("litert-lm")`:
  ```python
  173: if snapshot.state in (CatalogState.READY, CatalogState.EMPTY):
  174:     available_ids = {m.id.lower() for m in snapshot.models}
  ...
  178:     if resolved not in available_ids and model_name.lower() not in available_ids:
  179:         # Marks UNAVAILABLE
  ...
  196: status = ConfiguredModelStatus(model_id=model_name, state=ConfiguredModelState.VALID, ...)
  202: return ProviderReadiness(provider=config.provider, state=ProviderReadinessState.READY, can_infer=True, ...)
  ```
  If `snapshot.state` is `COLD`, `LOADING`, or `ERROR`, the availability check is completely bypassed! The function falls through to line 196 and returns `READY` with `can_infer=True`, even if the model has never been downloaded.
- **Impact:**
  Gestures and UI components believe the local runtime is ready to infer. When the user executes a shortcut, the use case fails downstream with an unhandled `LiteRTServerError`.

### Finding F5 [CONFIRMED]: Disjoint Download Tracking & Unmanaged Threads
- **Location:**
  - `addon/globalPlugins/AI-assistant/service/model_cache.py:190–195, 212–218`
  - `addon/globalPlugins/AI-assistant/providers/litert_manager.py:180–196`
  - `addon/globalPlugins/AI-assistant/providers/llama_manager.py:158–164`
  - `addon/globalPlugins/AI-assistant/ui/model_manager.py:66, 506–535`
- **Evidence:**
  - `ModelCatalogCache` spawns raw unmanaged daemon threads `ModelCatalogPreload` and `ModelCatalogFetch-{provider_id}`.
  - `ui/model_manager.py` tracks in-flight downloads in an ephemeral GUI instance set `self._pending_downloads`.
  - LiteRT downloads are handled via `ModelDownloadService` (`.part` file with byte progress).
  - llama.cpp HuggingFace GGUF downloads are handled opaquely inside `llama-server` process execution with zero byte progress callbacks.
  - If a download is triggered from one surface (e.g. settings or background preload), other surfaces have no visibility into the progress or cancellation state.

### Finding F6 [CONFIRMED]: Divergent Disk Cache Layouts
- **Location:**
  - `addon/globalPlugins/AI-assistant/providers/runtime/model_download.py:240–245` (`models/litert-lm/`)
  - `addon/globalPlugins/AI-assistant/providers/runtime/llama_models.py:361–364` (`models/llama-cpp/`)
  - `addon/globalPlugins/AI-assistant/embeddings/manager.py:21–26` (`models/embeddings/`)
- **Evidence:**
  Three completely independent folder hierarchies exist under `%APPDATA%/nvda/AIAssistant/models/`:
  - `models/litert-lm/`: Contains raw `.litertlm` downloads and `.part` files. However, the LiteRT runtime supervisor maintains a *second* internal registry at `~/.litert-lm` or an add-on-owned registry directory, leading to duplicate files.
  - `models/llama-cpp/`: Contains `models.json` and `models.ini`, but GGUF files may reside anywhere on the user's hard drive or in the server's cache.
  - `models/embeddings/`: Managed directly by the native Rust Candle engine.

### Finding F7 [CONFIRMED]: Isolated Embedding Stack & Missing Modalities
- **Location:**
  - `addon/globalPlugins/AI-assistant/embeddings/manager.py:29–105`
  - `addon/globalPlugins/AI-assistant/ui/embedding_model_dialog.py:19–196`
- **Evidence:**
  The embedding engine has its own isolated service (`EmbeddingModelService`) and its own dedicated dialog (`EmbeddingModelManagementDialog`). It does not report capabilities, catalog snapshots, or readiness to `ModelCatalogCache` or `ProviderReadinessService`. Furthermore, OCR, Transcription (Whisper), and TTS have zero model management abstractions.

### Finding F8 [CONFIRMED]: Negative Visibility Filtering Duplication & Leaks
- **Location:**
  - `addon/globalPlugins/AI-assistant/service/provider_controls.py:131–133`
  - `addon/globalPlugins/AI-assistant/service/provider_readiness.py:135–156`
  - `addon/globalPlugins/AI-assistant/ui/settings_panel.py:177–184`
  - `addon/globalPlugins/AI-assistant/ui/session_state.py:382–390`
- **Evidence:**
  `ModelVisibilityStore` is queried independently across multiple layers. In `ui/settings_panel.py`:
  ```python
  182: current = self._current_model_name(provider_id)
  183: if current and current not in choices:
  184:     choices.insert(0, current)
  ```
  If a user explicitly disabled a model in `ModelVisibilityStore`, but that model was currently active in settings, `settings_panel.py` forcefully re-injects it into the visible combo box, contradicting the user's visibility preference.

### Finding F9 [CONFIRMED]: Throwaway Provider Instantiation
- **Location:**
  - `addon/globalPlugins/AI-assistant/service/provider_catalog.py:35–39`
- **Evidence:**
  `ProviderCatalogService.list_models()` creates a brand new provider instance via `ProviderFactory.create_provider(config)`, calls `provider.list_models()`, and then closes it in `finally: provider.close()`. For cloud providers or HTTP backends, this repeatedly initializes network clients, connection pools, and credentials for a single discovery query.

---

## 4. Target Model Management Architecture: Central `ModelManagementService` (Invariants A11–A15)

To satisfy Invariants A11–A15, the target architecture consolidates all model-related responsibilities into a centralized application `ModelManagementService` operating in pure Python on the application side and delegating heavy operations (downloads, file verification, model loading) to the background worker process.

### 4.1 Topology & Collaborator Decomposition

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                  NVDA Shell / UI / Gestures                            │
│    (Presenter, SettingsPanel, ModelManagerDialog, WebUI SessionState, GestureHandler)  │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Non-blocking queries & typed events
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Central ModelManagementService (Application)                    │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │ Unified Model Registry (Invariant A11)                                         │   │
│   │ - Modalities: CHAT, VISION, OCR, TRANSCRIPTION, EMBEDDING, TTS                 │   │
│   │ - Immutable ModelDescriptor & Capability Index                                 │   │
│   ├────────────────────────────────────────────────────────────────────────────────┤   │
│   │ Central Download State Machine (Invariant A12)                                 │   │
│   │ - Single-flight deduplication, Byte Progress, SHA-256, Resume-Aware            │   │
│   ├────────────────────────────────────────────────────────────────────────────────┤   │
│   │ Storage & Disk Cache Layout (Invariant A13)                                    │   │
│   │ - Unified `%APPDATA%/.../models/` tree, atomic renaming, source protection     │   │
│   ├────────────────────────────────────────────────────────────────────────────────┤   │
│   │ Non-Blocking Readiness & Negative Visibility (Invariant A14)                   │   │
│   │ - Event-driven readiness cache, Centralized disabled filtering, No fallbacks   │   │
│   ├────────────────────────────────────────────────────────────────────────────────┤   │
│   │ Multi-Modal Resource Arbitration & Coexistence Engine (Invariant A15)          │   │
│   │ - VRAM/RAM budgets, Model eviction, Context arbitration, GPU serialization    │   │
│   └───────────────────────────────────────┬────────────────────────────────────────┘   │
└───────────────────────────────────────────┼────────────────────────────────────────────┘
                                            │ Worker IPC Protocol (Versioned)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Out-of-Process Worker Engine                              │
│   ┌───────────────────┬───────────────────┬───────────────────┬───────────────────┐    │
│   │   Chat / LLM      │    Vision Engine  │    OCR Engine     │   Transcription   │    │
│   │ (LiteRT / llama)  │  (ViT / VLM Hub)  │ (Paddle / TrOCR)  │   (Whisper.cpp)   │    │
│   ├───────────────────┴───────────────────┴───────────────────┴───────────────────┤    │
│   │        Native Runtime Supervisor (Rust/PyO3) & Native Embedding Engine        │    │
│   └───────────────────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 4.2 Invariant A11: Unified Model Metadata & Registry across Multi-Modalities

No modality or runtime shall maintain its own isolated model metadata struct. All models across all six modalities are defined by the immutable `ModelDescriptor`.

#### Modality Taxonomy
```python
class Modality(str, Enum):
    CHAT = "chat"
    VISION = "vision"
    OCR = "ocr"
    TRANSCRIPTION = "transcription"
    EMBEDDING = "embedding"
    TTS = "tts"
```

#### Unified `ModelDescriptor` Specification
```python
@dataclass(frozen=True, slots=True)
class ModelResourceSpec:
    """Estimated memory and compute footprint for resource arbitration."""
    ram_bytes: int                     # Required system RAM in bytes
    vram_bytes: int                    # Required GPU VRAM in bytes (0 if CPU-only)
    compute_target: Literal["cpu", "gpu", "npu", "universal"] = "universal"
    context_window: int | None = None  # Relevant for LLM / embedding


@dataclass(frozen=True, slots=True)
class ModelSourceSpec:
    """Artifact retrieval source."""
    kind: Literal["cloud_endpoint", "huggingface_file", "huggingface_repo", "direct_url", "local_file"]
    location: str                      # URL, HF repo ID, or local filesystem path
    filename: str                      # Stored artifact filename
    revision: str = "main"
    sha256: str | None = None
    auth_required: bool = False        # Gated / credentials required


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Canonical model descriptor shared across all modalities."""
    model_id: str                      # Unique model identifier (e.g. 'gemma-4-e2b-cpu')
    display_name: str                  # User-facing label (e.g. 'Google Gemma 4 E2B (CPU)')
    provider_id: str                   # Backend runtime family (e.g. 'litert-lm', 'llama-cpp', 'candle', 'whisper')
    modality: Modality                 # Primary modality
    capabilities: frozenset[str]       # Normalized capabilities (e.g. 'streaming', 'thinking', 'tools')
    source: ModelSourceSpec
    resources: ModelResourceSpec
    priority: int = 100                # Lower is more recommended (<= 50 = recommended)
    description: str = ""
    canonical_group_id: str | None = None # Parent model ID when this descriptor is a hardware variant
```

---

### 4.3 Invariant A12: Centralized Download State Machine & Worker Offload

All downloading, checksum verification, and artifact staging are coordinated by the central service and executed in the background worker process. The UI dialog and background preloader never perform direct HTTP requests.

#### Deterministic Download Lifecycle
```
                     ┌──────────────────┐
                     │  NOT_INSTALLED   │
                     └────────┬─────────┘
                              │ enqueue_download()
                              ▼
                     ┌──────────────────┐
                     │      QUEUED      │
                     └────────┬─────────┘
                              │ worker claims job
                              ▼
                     ┌──────────────────┐ ◄────────────────┐
                     │   DOWNLOADING    │                  │
                     └────────┬─────────┘                  │ HTTP Range Resume
                              │ (progress: bytes, rate, ETA)
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
      [Cancel / Network Error]        [Download Complete]
               │                             │
               ▼                             ▼
      ┌──────────────────┐          ┌──────────────────┐
      │  CANCELLED/PAUSED│          │    VERIFYING     │ (SHA-256 check)
      │  (.part retained)│          └────────┬─────────┘
      └──────────────────┘                   │
                                             ▼
                                    ┌──────────────────┐
                                    │    PREPARING     │ (Extract/Stage/Register)
                                    └────────┬─────────┘
                                             │
                              ┌──────────────┴──────────────┐
                              ▼                             ▼
                     ┌──────────────────┐          ┌──────────────────┐
                     │    INSTALLED     │          │      FAILED      │
                     │  (Ready for use) │          │(Error message)   │
                     └──────────────────┘          └──────────────────┘
```

#### Download State DTO
```python
class DownloadStatus(str, Enum):
    NOT_INSTALLED = "not_installed"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    PREPARING = "preparing"
    INSTALLED = "installed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DownloadProgressSnapshot:
    model_id: str
    status: DownloadStatus
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bytes_per_sec: float = 0.0
    eta_seconds: float | None = None
    error_message: str | None = None
```

---

### 4.4 Invariant A13: Standardized Disk Cache & Storage Layout

Consolidate the fragmented directories into a single, predictable directory layout under `%APPDATA%/nvda/AIAssistant/models/`.

#### Standardized Directory Structure
```
%APPDATA%/nvda/AIAssistant/models/
├── inventory.json                    # Single authoritative catalog manifest of installed models
├── staging/                          # In-flight partial downloads
│   ├── <model_id>.part               # Resumable partial file
│   └── <model_id>.meta.json          # Resume metadata (ETag, expected SHA-256, URL)
├── chat/
│   ├── litert-lm/
│   │   └── <model_id>/
│   │       └── model.litertlm        # Atomically moved from staging
│   └── llama-cpp/
│       ├── models.ini                # Preserved router preset
│       └── <model_id>/
│           └── model.gguf
├── vision/
│   └── <model_id>/                   # Dedicated vision models
├── ocr/
│   └── <model_id>/                   # OCR models (PaddleOCR / TrOCR / Nougat)
├── transcription/
│   └── whisper/
│       └── <model_id>/
│           └── ggml-<model>.bin      # Whisper.cpp models
├── embeddings/
│   └── <model_id>/                   # Candle embeddings (safetensors + tokenizer.json)
└── tts/
    └── <model_id>/                   # Future local neural TTS models
```

#### Storage Invariants:
1. **Atomic Installation:** Files are downloaded into `staging/<model_id>.part`. Upon successful SHA-256 verification, they are atomically moved into their destination path.
2. **User Source Protection:** When a user imports a local file, `ModelManagementService` creates a hard link or manifest reference. It **never deletes or modifies user-owned files** upon model deletion.
3. **Inventory Isolation:** `inventory.json` is the sole source of truth for installed local models, updated atomically using temporary files and directory replace operations.

---

### 4.5 Invariant A14: Non-Blocking Readiness Probing & Zero Silent Fallbacks

#### Probing Rules:
1. **Zero Main-Thread Sockets:** No TCP connections, HTTP probes, or file hash verifications may execute synchronously on the NVDA thread or during `evaluate()`.
2. **Event-Driven Readiness Cache:** The service maintains an in-memory `ReadinessSnapshot`. Runtime health updates are pushed asynchronously from the supervisor/worker via IPC notifications.
3. **Centralized Negative Visibility:** `ModelVisibilityStore` is owned exclusively by `ModelManagementService`. Disabled models are filtered out at the service boundary.
4. **Strict Fail-Closed Policy (No Silent Fallback):**
   - If a configured model is not installed, the service reports `ConfiguredModelState.UNAVAILABLE` with reason `MODEL_UNAVAILABLE`.
   - Under no circumstances will the system silently mutate settings or select a different model without explicit user action.
   - The UI presents a clear message: `"Model {model_name} is not installed. Press Enter to open Model Manager to download it."`

---

### 4.6 Invariant A15: Multi-Modal Resource Arbitration & Coexistence Engine

Running multiple local models concurrently (e.g. an LLM alongside an OCR model and a Whisper transcription session) on consumer hardware will lead to out-of-memory crashes or severe GPU thrashing without proactive arbitration.

#### Memory Budget & Arbitration Table
| Hardware Profile | System RAM | Detected VRAM | Allowed Concurrent Models | Allocation Policy |
| :--- | :--- | :--- | :--- | :--- |
| **Low-End (Integrated / CPU)** | < 16 GB | < 2 GB | 1 Active Model | Strict exclusive locking: unloading previous model before loading new modality. |
| **Mid-Range (Budget GPU)** | 16–32 GB | 4–6 GB | 1 GPU LLM + 1 CPU Helper | LLM on GPU (capped context 4K–8K); OCR/Embedding pinned to CPU/XNNPACK. |
| **High-End (Discrete GPU)** | >= 32 GB | >= 8 GB | 1 GPU LLM + 1 GPU OCR / Whisper | Dynamic VRAM partitioning: 70% VRAM reserved for LLM, 30% for OCR/Whisper. |

#### Coexistence Rules:
1. **Preemptive Idle Reaper:** An OCR or Vision model loaded for a one-shot screenshot is unloaded after an idle timeout (e.g. 60 seconds) to return VRAM to the chat model.
2. **GPU Context Serialization:** Heavy GPU compute passes (e.g. OCR image preprocessing and LLM generation) are scheduled through a cooperative GPU execution queue in the worker to prevent D3D12/Vulkan driver timeout detection (TDR) crashes.
3. **Graceful Fallback to CPU:** If GPU memory allocation fails when loading an OCR or Embedding model, the service automatically configures that model on the CPU backend while keeping the primary LLM on the GPU, logging an informational notice rather than crashing.

---

## 5. Collaborator Interfaces & Modality Engines

The central `ModelManagementService` coordinates smaller, dedicated collaborators per modality:

```python
class ModalityEngineCollaborator(Protocol):
    """Protocol implemented by modality-specific backend coordinators."""
    modality: Modality

    def discover_models(self) -> tuple[ModelDescriptor, ...]:
        """Return all discoverable models for this modality."""
        ...

    def verify_runtime_ready(self, model: ModelDescriptor) -> bool:
        """Non-blocking check if the execution runtime is ready."""
        ...

    def prepare_model(self, model: ModelDescriptor, cancel_event: threading.Event) -> Path:
        """Stage, download, or verify model artifacts."""
        ...

    def release_resources(self, model_id: str) -> None:
        """Unload model from memory if inactive."""
        ...
```

### Specific Modality Collaborators:
1. **`ChatModelCollaborator`:** Coordinates LiteRT-LM and llama.cpp text/chat models.
2. **`VisionModelCollaborator`:** Coordinates multimodal vision encoders and standalone image analysis models.
3. **`OcrModelCollaborator`:** Coordinates lightweight OCR engines (Slice 9) with bounded memory allocations.
4. **`TranscriptionModelCollaborator`:** Coordinates Whisper.cpp speech models (Slice 10) with audio streaming buffers.
5. **`EmbeddingModelCollaborator`:** Coordinates Candle/Rust safetensor embeddings, replacing the isolated `EmbeddingModelService`.
6. **`TtsModelCollaborator`:** Foundation for future local neural text-to-speech models.

---

## 6. Migration Strategy (Alignment with Slices 0–10)

The consolidation of model management maps directly into the project migration slices:

- **Slice 0 (Audit & Architecture Contract):** Establish this audit report and freeze the multi-modal `ModelDescriptor` contract.
- **Slice 4 (Heavy Operation Offload - Model Download):** Move HTTP streaming, Range resumption, and SHA-256 verification from NVDA process into the out-of-process worker.
- **Slice 5 (Model Management Application Boundary):** Introduce `ModelManagementService` in pure Python, deprecate `service/model_cache.py` and `providers/model_manager.py`, and centralize negative visibility filtering.
- **Slice 6 (LiteRT Runtime Ownership Moved to Worker):** Worker owns the LiteRT supervisor process and model catalog ingestion.
- **Slice 7 (llama.cpp Runtime Ownership Moved to Worker):** Worker owns `llama-server` process, preset generation, and model switching.
- **Slice 8 (Removal of Obsolete NVDA-Side Runtime Threading):** Delete `ModelCatalogPreload`, `BrowserAssistantModelPreload`, and raw daemon threads from `plugin/background.py`.
- **Slice 9 (OCR Session Foundation):** Integrate `OcrModelCollaborator` into `ModelManagementService` under Invariant A15 coexistence rules.
- **Slice 10 (Transcription Session Foundation):** Integrate `TranscriptionModelCollaborator` with bounded audio memory buffering.

---

## 7. Verification Method & Test Suite Alignment

### Independent Verification Steps:
1. **Pure-Python Unit Tests:**
   - Test `ModelDescriptor` construction and validation across all six modalities.
   - Test `DownloadStateMachine` transitions (`QUEUED` -> `DOWNLOADING` -> `VERIFYING` -> `INSTALLED`).
   - Test non-blocking `ReadinessEvaluator` ensuring zero network sockets or disk I/O on evaluation.
   - Test negative visibility filtering ensuring explicitly disabled models are never presented or selected.
2. **Resource Arbitration Tests:**
   - Simulate concurrent LLM + OCR requests under 4 GB VRAM limit and verify OCR falls back to CPU or serializes execution without memory thrashing.
3. **Regression Tests:**
   - Execute baseline suite: `uv run pytest tests/service/test_configured_model_status.py tests/config/test_model_visibility.py tests/service/test_model_cache.py`.
   - Verify zero unhandled exceptions or thread leaks.
