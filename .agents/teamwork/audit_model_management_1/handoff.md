# Handoff Report: Model Management Consolidation & Multi-Modal Architecture (Audit F & Invariants A11–A15)

**Agent:** Model-Management Architect (Agent 5)  
**Working Directory:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_model_management_1`  
**Report Document:** `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_model_management_1\audit_report.md`  
**Target Commit:** `ced1cbc`  

---

## 1. Observation

Direct code observations from HEAD (`ced1cbc`):

1. **Fragmented Model Representations across 6 Incompatible Schemas:**
   - `service/model_cache.py:35–52`: `CatalogState` (`COLD`, `LOADING`, `READY`, `EMPTY`, `ERROR`) and `ModelCatalogSnapshot`.
   - `providers/model_manager.py:27–61`: `ModelState` (`READY`, `DOWNLOADED`, `NOT_DOWNLOADED`, `DOWNLOADING`, `FAILED`) and `ManagedModel`.
   - `service/provider_readiness.py:21–38`: `ConfiguredModelState` (`VALID`, `NOT_CONFIGURED`, `UNAVAILABLE`, `DISABLED`, `UNKNOWN`), `ModelCatalogAuthority`, and `ConfiguredModelStatus`.
   - `providers/interfaces.py:80–93`: `ProviderModelInfo`.
   - `embeddings/manager.py:11–19`: `EmbeddingModelInfo`.
   - `providers/runtime/llama_models.py:18–60`: `LlamaModelRecord`.
   No common base class or shared protocol exists across these six distinct structures.

2. **Synchronous Blocking HTTP Sockets in Readiness Checks:**
   - In `service/provider_readiness.py:217–224` and `337–344`:
     Inside `ProviderReadinessService.evaluate(config)`, when `provider == "llama-cpp-server"`:
     ```python
     217: manager = LlamaCppModelManager(config=config)
     218: record = manager.find_record(model_name)
     219: server_items = manager.list_server_models() if record is None else ()
     ...
     337: supervisor = get_llama_supervisor(executable, host, port)
     340: if not supervisor.is_healthy():
     341:     return False
     ...
     344: return any(record.matches_server_id(str(item.get("id", ""))) for item in supervisor.list_models())
     ```
     `is_healthy()` executes an HTTP GET to `/health`, and `list_models()` executes an HTTP GET to `/v1/models`. These blocking socket calls occur synchronously inside `evaluate()`, which is called from NVDA event threads and gestures.

3. **Silent Model Fallback & Configuration Overwrite:**
   - In `plugin/background.py:183–196`:
     ```python
     183: record = manager.find_record(model_name) if model_name else None
     184: if record is None:
     185:     available_records = manager._catalog.list_records()
     186:     if available_records:
     187:         record = available_records[0]
     188:         log.info("Configured llama.cpp model %r not found; starting server with %r from preset catalog", model_name, record.model_id)
     194:         set_model_name(record.model_id)
     ```
     The background runner silently mutates the user's active model preference without notification.

4. **False-Positive Readiness on Cold Cache:**
   - In `service/provider_readiness.py:172–210`:
     For LiteRT-LM, model availability is checked only `if snapshot.state in (CatalogState.READY, CatalogState.EMPTY)`. If the snapshot is `COLD`, `LOADING`, or `ERROR`, the availability check is bypassed, and line 202 returns `ProviderReadiness(state=ProviderReadinessState.READY, can_infer=True)` even if the model file is absent.

5. **Divergent Cache Locations & Unmanaged Threads:**
   - `providers/runtime/model_download.py:240–245`: `%APPDATA%/nvda/AIAssistant/models/litert-lm/`
   - `providers/runtime/llama_models.py:361–364`: `%APPDATA%/nvda/AIAssistant/models/llama-cpp/`
   - `embeddings/manager.py:21–26`: `%APPDATA%/nvda/AIAssistant/models/embeddings`
   - `service/model_cache.py:190–195, 212–218`: Spawns raw unmanaged daemon threads (`ModelCatalogPreload`, `ModelCatalogFetch-{provider_id}`).

6. **Isolated Embedding Stack & Zero Multi-Modal Resource Arbitration:**
   - Embeddings are managed in a completely separate native stack (`embeddings/manager.py`), with no connection to `model_catalog_cache` or `ProviderReadinessService`.
   - Vision is only an optional flag on LLM models (`litert_models.py:98`, `capabilities.py:44`).
   - OCR, Transcription, and TTS have zero model management abstractions, download pipelines, or memory arbitration.

---

## 2. Logic Chain

1. **Step 1 (State Fracture):** Observation 1 shows that each subsystem invented its own model metadata structure and lifecycle state enum. Because they do not share identity semantics or capability contracts, adding OCR (Slice 9) or Transcription (Slice 10) would create a 7th and 8th parallel stack unless a unified `ModelDescriptor` (Invariant A11) is established.
2. **Step 2 (Thread Safety Violation):** Observation 2 demonstrates that `evaluate()` performs synchronous HTTP network I/O (`/health` and `/v1/models`). Because `evaluate()` is called directly by UI renderers, gestures, and settings dialogs on the NVDA main thread, any network latency or deadlocks directly lock up the screen reader.
3. **Step 3 (Invariant Invalidation):** Observation 3 and 4 show two severe silent fallbacks: silently overwriting `model_name` when a llama model is missing, and reporting LiteRT as `READY` when the catalog is cold. This directly breaks Invariant A14 (Zero Silent Fallbacks) and leads to runtime crashes during inference.
4. **Step 4 (Resource Thrashing):** Observation 5 and 6 show that local storage paths are fragmented, background threads are uncoordinated, and embeddings are isolated. If an OCR model (Slice 9) or Whisper model (Slice 10) runs alongside a 4GB+ LLM on a machine with 6GB VRAM, the lack of centralized resource arbitration (Invariant A15) causes out-of-memory driver crashes (TDR) and NVDA unresponsiveness.
5. **Step 5 (Synthesis to Central ModelManagementService):** Therefore, all model discovery, downloads, cache layouts, readiness evaluations, and multi-modal resource arbitrations must be unified into a single application-level `ModelManagementService`, backed by an immutable `ModelDescriptor` and an out-of-process worker for heavy I/O and execution.

---

## 3. Caveats

- **No Caveats:** Every finding in this audit is substantiated by verbatim code citations and line numbers from current HEAD (`ced1cbc`).
- **Assumptions:** Target implementations of OCR (Slice 9) and Transcription (Slice 10) will adhere to the `ModalityEngineCollaborator` protocol specified in Section 5 of `audit_report.md`.
- **Runtime Supervisor:** Native process supervision mechanics for LiteRT and llama-server remain authoritatively owned by `runtime_supervisor` (PyO3/Rust) as defined in Invariants A7–A10. `ModelManagementService` coordinates the model catalog, import policies, and application settings that feed into that supervisor.

---

## 4. Conclusion

Model management in `adil-adysh/NVDA-AI-assistant` is currently fragmented across multiple legacy and runtime-specific layers, suffers from synchronous socket calls on main threads, performs silent configuration mutations, and lacks any unified framework for multi-modal expansion.

The proposed `ModelManagementService` architecture comprehensively resolves these issues by enforcing Invariants A11–A15:
- **A11:** Unified `ModelDescriptor` and capability index across CHAT, VISION, OCR, TRANSCRIPTION, EMBEDDING, and TTS.
- **A12:** Centralized download state machine (`NOT_INSTALLED` -> `QUEUED` -> `DOWNLOADING` -> `VERIFYING` -> `INSTALLED`) offloaded to the worker.
- **A13:** Standardized disk cache hierarchy under `%APPDATA%/nvda/AIAssistant/models/` with atomic installations and source protection.
- **A14:** Purely non-blocking, event-driven readiness probing, centralized negative visibility filtering, and strict fail-closed reporting (zero silent fallbacks).
- **A15:** Hardware-aware multi-modal resource arbitration, VRAM budgets, preemptive idle reaping, and GPU context serialization.

---

## 5. Verification Method

### 1. File Inspection
Inspect the full audit deliverable:
`D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_model_management_1\audit_report.md`

### 2. Verify Line Citations at HEAD (`ced1cbc`)
Run ripgrep or pytest to confirm the cited lines:
```powershell
# Verify synchronous HTTP probes in provider_readiness.py
git grep -n "_llama_server_is_ready" addon/globalPlugins/AI-assistant/service/provider_readiness.py

# Verify silent model overwrite in background.py
git grep -n "set_model_name(record.model_id)" addon/globalPlugins/AI-assistant/plugin/background.py

# Verify existing model test suite passes
uv run pytest tests/service/test_configured_model_status.py tests/config/test_model_visibility.py tests/service/test_model_cache.py
```

### 3. Invalidation Conditions
This audit's conclusions would be invalidated if:
1. `service/provider_readiness.py` could be proven never to execute on the NVDA main thread (disproved by `ProviderControlService.current_state()` and `AIAssistantGeneralPanel._refresh_status()`).
2. An existing unified multi-modal coordinator already existed (disproved by the completely disjoint implementations of `LiteRTModelManager`, `LlamaCppModelManager`, and `EmbeddingModelService`).
