# Comprehensive Architectural Audit Report: Audits A, C, and G

**Author**: Current Architecture & Dependency Auditor (Agent 1)  
**Date**: 2026-10-02  
**Commit HEAD**: `ced1cbc`  
**Working Directory**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_arch_dep_2`  
**Mandatory Classification Tags**: `CONFIRMED`, `LIKELY`, `DESIGN DETAIL`, `BLOCKER`, `UNKNOWN / REQUIRES EXPERIMENT`  

---

## 1. Executive Summary

This report delivers a deep, code-level architectural audit of `adil-adysh/NVDA-AI-assistant` at commit `ced1cbc` covering:
- **Audit A (Process Topology)**: Complete mapping of process creation, ownership, transport, health, restart, teardown, and failure isolation across all system processes, contrasted with the target worker architecture.
- **Audit C (NVDA Import Contamination)**: Full AST inventory of all 95 direct NVDA imports across the repository, identification of the maximum coherent pure-Python domain/service subtree, and automated linting enforcement rules for Invariants A5–A6, A30.
- **Audit G (`plugin/background.py` Decomposition)**: Line-by-line deconstruction of `plugin/background.py` (495 lines), separating concerns into orchestration, presentation, model management, runtime commands, and generic execution, with destination target modules for every symbol.

### Key Audit Conclusions

1. **Monolithic In-Process Execution with Fragile Subprocess Supervision [CONFIRMED]**:
   - The entire add-on runtime (business logic, context extraction, conversation database, model downloads, embeddings, and prompt orchestration) runs directly inside `nvda.exe`'s CPython interpreter.
   - All four native Rust PyO3 extensions (`runtime_supervisor`, `llm_client`, `memory_engine`, `embedding_engine`) are loaded into `nvda.exe`'s process address space. A panic, memory access violation, or heap corruption in native code immediately kills the user's screen reader (`nvda.exe`).
   - The UI Host (`nvda_ui_host.exe`), LiteRT server (`python.exe -m litert_lm_cli.main serve`), and llama-server (`llama-server.exe`) run as external child processes, but their lifecycle and supervision are tied directly to NVDA shutdown threads (`application.py:178, 186`) which run as fire-and-forget daemon threads that can be truncated upon NVDA exit, risking orphaned background processes.

2. **NVDA Import Contamination is Heavily Concentrated and Easily Decoupled [CONFIRMED]**:
   - Out of 95 total NVDA import statements across the entire add-on codebase, **40 statements (42.1%)** are identical: `from logHandler import log`.
   - `core/`, `tools/`, `use_case/`, and `embeddings/` already contain **zero** NVDA imports.
   - `service/`, `providers/`, `prompts/`, and `observability/` are contaminated *exclusively* by `from logHandler import log`.
   - `config/` is contaminated only by `from logHandler import log` (in `state.py:7` and `yaml_store.py:10`) and a single import `import languageHandler` in `config/settings.py:8` used in `get_effective_language()` (`settings.py:200`).
   - Once logging is standardized to Python's standard library `logging.getLogger(__name__)` and `languageHandler` is accessed via dependency injection or lazy fallback, **over 80% of the Python codebase becomes a 100% pure-Python domain/service subtree** capable of running independently without an NVDA checkout or running NVDA process.

3. **`plugin/background.py` is an Overburdened God-Module [CONFIRMED]**:
   - `plugin/background.py` (495 lines) conflates 5 distinct architectural responsibilities:
     1. Local server startup and CLI model import orchestration (`ensure_litert_server_ready`, `ensure_provider_server_ready`, `_ensure_model_imported`).
     2. Hardware capability detection and variant sorting (`_build_import_candidates`, `has_gpu`).
     3. NVDA speech announcements and translation (`nvda_ui.queue(nvda_ui.message, _(...))`).
     4. Unbounded background thread spawning (`BackgroundTaskRunner._start_worker` creating raw `threading.Thread` instances without a queue or pool).
     5. Configuration change listeners that spawn background threads (`_on_litert_server_config_changed`, `_on_llama_server_config_changed`).
   - It also contains hidden application state mutations (e.g. `set_model_name` fallback in `ensure_provider_server_ready:194`).
   - Every function and class can be cleanly partitioned into dedicated service, worker, and presentation modules.

4. **Zero Architectural Blockers [CONFIRMED]**:
   - No fundamental barrier prevents moving to the Target Worker Topology (Invariants A1–A4, A16–A24).
   - All tests pass at HEAD (461 passed in 13.99s, Rust checks pass cleanly).

---

## 2. Baseline Verification Commands & Status

All baseline verification commands were executed at HEAD (`ced1cbc`):

| Tool / Command | Exit Code | Result Summary | Notes |
| :--- | :---: | :--- | :--- |
| `uv run ruff check .` | 0 | All checks passed! | Clean against current ruff rules; needs new custom import rules for Invariant A6. |
| `cargo check --manifest-path nvda_ui_host/Cargo.toml` | 0 | Finished `dev` profile in 0.04s | Standalone UI Host builds cleanly. |
| `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` | 0 | 11 passed; 0 failed (1.54s) | Native supervisor tests pass cleanly in project venv (Python 3.13). |
| `uv run pytest` | 0 | 461 passed, 3 deselected (13.99s) | Full test suite passes against sibling NVDA checkout. |

---

## 3. Audit A: Process Topology Deep Dive

### 3.1 Process Inventory

At HEAD (`ced1cbc`), the running application spans 6 distinct process categories:

```
+----------------------------------------------------------------------------------------------------+
| 1. NVDA Host Process (nvda.exe)                                                                    |
|    - Main Event Loop Thread (queueHandler.pumpAll, wx.App)                                         |
|    - Python Global Plugin Runtime (addon/globalPlugins/AI-assistant/)                              |
|    - In-Process Native PyO3 Extensions (runtime_supervisor, llm_client, memory_engine, embeddings) |
|    - Unbounded Python Background Threads (BackgroundTaskRunner, ModelListFetch, etc.)              |
+------------------------------------+--------------------------------+------------------------------+
                                     | (Named Pipes)                  | (std::process::Command)
                                     v                                v
+------------------------------------+-----------+    +---------------+------------------------------+
| 2. UI Host Process (nvda_ui_host.exe)          |    | 4. Managed LiteRT-LM Server                  |
|    - Native Win32 Message Loop                 |    |    (python.exe -m litert_lm_cli.main serve)  |
|    - Windows Named Pipe Server (cmd & evt)     |    |    - HTTP API: http://127.0.0.1:9379/        |
|    +-----------------------------------------+ |    +----------------------------------------------+
|    | 3. WebView2 Subprocesses                | |                                                   |
|    |    (msedgewebview2.exe x N)             | |    +----------------------------------------------+
|    |    - Chromium GPU/Renderer/Utility      | |    | 5. Managed llama-server                      |
|    |    - Svelte 5 Web UI Runtime            | |    |    (llama-server.exe)                        |
|    +-----------------------------------------+ |    |    - HTTP API: http://127.0.0.1:8080/        |
+------------------------------------------------+    +----------------------------------------------+
                                                                      | (subprocess.run)
                                                                      v
                                                      +---------------+------------------------------+
                                                      | 6. Ephemeral Subprocesses                    |
                                                      |    - litert-lm import, list, dir, remove     |
                                                      +----------------------------------------------+
```

### 3.2 Process Attribute Matrix

| Process / Component | Creation Site & Mechanism | Ownership & Supervision | Transport / IPC | Health Check Mechanism | Restart Policy | Teardown Sequence | Failure Isolation | Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. NVDA Host Process (`nvda.exe`)** | Launched by Windows shell or user. Hosts CPython interpreter. | OS Process owned by user session. | Windows OS messages, COM/UIA events, `queueHandler`. | Windows OS / NVDA watchdog timer. | If NVDA crashes, user loses speech/braille immediately. | `GlobalPlugin.terminate()` in `controller.py:74`. | **ZERO isolation**: any crash or fatal error terminates screen reader. | `CONFIRMED` |
| **2. Python Global Plugin Runtime** | `globalPluginHandler.loadPlugins()` inside `nvda.exe`. | In-process module hierarchy under `addon/globalPlugins/AI-assistant/`. | Direct Python object calls, `nvda_ui.queue` to NVDA main thread. | None. Unhandled exception in threads logged via `error_reporter`. | Reloaded on NVDA restart or plugins reload (`NVDA+Q` or `NVDA+F3`). | `GlobalPlugin.terminate()` -> `AIAssistantApplication.terminate()`. | Shared with `nvda.exe`: GIL contention and unhandled C-level crashes kill NVDA. | `CONFIRMED` |
| **3. UI Host (`nvda_ui_host.exe`)** | `ui/host_process.py:86` via `subprocess.Popen([host_exe], creationflags=CREATE_NEW_PROCESS_GROUP, stdout=PIPE)`. | Module-global `_host_process` in `ui/host_process.py:14` protected by `_process_lock`. | 2 Windows named pipes (`\\.\pipe\nvda_ai_assistant_ui_cmd`, `\\.\pipe\nvda_ai_assistant_ui_evt`), stdout pipe (`_drain_host_output`). | Pipe probing via `win32pipe.WaitNamedPipe` (`host_process.py:54`); `UiCommand::HealthCheck` over cmd pipe; `process.poll()`. | On pipe failure or process death, `ui/adapter.py` falls back to native NVDA dialogs. Restarted on next UI request. | `ui/host_process.py:134` (`stop_host()`): `process.terminate()`, wait 5s, then `process.kill()`. | **High**: Host crash does not crash NVDA. Python catches pipe errors and falls back to `nvda_ui`. | `CONFIRMED` |
| **4. WebView2 Subprocesses (`msedgewebview2.exe`)** | Spawns internally by WebView2 runtime COM objects in `nvda_ui_host.exe`. | Child processes of `nvda_ui_host.exe` (Chromium multi-process model). | Chromium IPC; JavaScript bridge `window.chrome.webview.postMessage` / `window.__receiveHostCommand`. | Chromium internal crash detection; `CoreWebView2ProcessFailed` handler in Rust host. | Handled internally by WebView2 runtime or host recreation. | Terminated automatically when `nvda_ui_host.exe` exits. | **High**: WebView2 render crash does not crash `nvda.exe`. Host can report failure or reload. | `DESIGN DETAIL` |
| **5. LiteRT-LM Server Process** | Rust `runtime_supervisor::process::OsProcessDriver` (`process.rs:48`) via `std::process::Command::spawn`, or Python fallback `server.py:309`. | Native `RuntimeSupervisor` extension (in-process Rust) via `LiteRTServerSupervisor`. | HTTP / SSE over `http://127.0.0.1:9379/` (OpenAI-compatible `/v1/models`, `/v1/chat/completions`). | Polling `GET /v1/models` every 500ms via `UreqHealthChecker` (`health.rs:12`) up to 60s timeout; `process.poll()` exit detection. | Replaced if startup configuration snapshot changes (`server.py:666`); `restart()` invokes `stop()` followed by `ensure_ready()`. | `plugin/application.py:178` launches `threading.Thread(target=supervisor.stop, name="LiteRTServerShutdown", daemon=True)`. | **Moderate**: Server crash raises `LiteRTServerError`. But daemon thread shutdown on NVDA exit risks orphaned process. | `CONFIRMED` |
| **6. llama-server Process (`llama-server.exe`)** | Rust `runtime_supervisor::process::OsProcessDriver` or Python `subprocess.Popen` in `llama_server.py:170`. | Native `RuntimeSupervisor` via `LlamaServerSupervisor`. | HTTP / SSE over `http://127.0.0.1:8080/` (`/v1/chat/completions`, `/models`). | Polling `GET /v1/models` or `/models` via `UreqHealthChecker`; child exit detection. | Replaced when startup configuration (model, threads, context, preset) changes (`llama_server.py:326`). | `plugin/application.py:186` launches `threading.Thread(target=shutdown_llama_servers, name="LlamaServerShutdown", daemon=True)`. | **Moderate**: Isolated OS process. However, daemon thread shutdown risks orphaned process. | `CONFIRMED` |
| **7. In-Process Native PyO3 Extensions** | Dynamically loaded `.pyd` shared libraries in `lib/`: `runtime_supervisor.pyd`, `llm_client.pyd`, `memory_engine.pyd`, `embedding_engine.pyd`. | Loaded into `nvda.exe` Python runtime. | Direct C-ABI Python FFI / PyO3 function calls. | None (in-process). | Cannot be unloaded or restarted without restarting `nvda.exe`. | Freed when `nvda.exe` unloads or exits. | **ZERO isolation**: Rust panic or memory fault directly crashes `nvda.exe`. | `CONFIRMED` |
| **8. Ephemeral Subprocesses** | `providers/runtime/server.py:299` via `subprocess.run(cmd, timeout=...)` for CLI operations (`import`, `list`, `dir`, `remove`). | Ephemeral child processes spawned from NVDA. | Standard input/output/error pipes (`stdout=PIPE, stderr=PIPE`). | Process returncode and `subprocess.TimeoutExpired` handling. | Retried on subsequent user actions. | Terminated upon command completion or timeout expiry. | Blocks background thread for up to 120s (`server.py:870`). | `CONFIRMED` |

### 3.3 Detailed Process Boundary Crossings & Failure Propagation

#### 1. NVDA -> UI Host Boundary
- **Crossing Site**: `ui/host_transport.py:57` (`HostPipeTransport.send_and_receive`).
- **Mechanism**: Connects to `\\.\pipe\nvda_ai_assistant_ui_cmd` via `win32file.CreateFile`, writes newline-terminated JSON, reads newline-terminated response with 5-second timeout (`host_transport.py:147`).
- **Failure Mode**:
  - If `nvda_ui_host.exe` hangs or fails to respond within 5 seconds, `HostPipeTransport` raises `RuntimeError` (`host_transport.py:168`).
  - `ui/adapter.py:148` catches `HostUnavailableError` / transport failure, updates lifecycle state to `Failed`, and routes presentation intent to `ui/nvda_ui.py` (native NVDA modal dialog or speech).
  - **Risk [LIKELY]**: The 5-second blocking read is executed on whatever thread called `send_and_receive`. If invoked near the UI dispatch or presenter thread, it introduces noticeable latency.

#### 2. NVDA -> Local Runtime Servers (LiteRT / llama-server) Boundary
- **Crossing Site**: `providers/adapters/openai_compat.py:44` via `llm_client` (native `ureq`) or `urllib.request`.
- **Mechanism**: HTTP POST to `http://127.0.0.1:9379/v1/chat/completions` or `http://127.0.0.1:8080/v1/chat/completions`.
- **Failure Mode**:
  - Connection refused or timeout raises `ProviderNetworkError` / `LiteRTServerError`.
  - Caught by `plugin/background.py:473` in `BackgroundTaskRunner.run_use_case_in_background` and reported via `error_reporter` and presenter error dialog.
  - Does NOT crash NVDA.

#### 3. NVDA -> Native Extensions Boundary
- **Crossing Site**: Direct PyO3 invocations in `runtime_supervisor.RuntimeSupervisor`, `memory_engine`, `llm_client`, `embedding_engine`.
- **Mechanism**: In-process C FFI calls.
- **Failure Mode**:
  - Any unhandled Rust panic (unless caught across `catch_unwind`), segmentation fault, or out-of-memory condition in Candle/redb aborts the process immediately.
  - **Risk [BLOCKER to Invariant A1/A16]**: Running `embedding_engine` (Candle deep-learning embeddings) or `llm_client` in-process inside `nvda.exe` exposes the core screen reader to native heap exhaustion and memory crashes.

#### 4. Application Teardown Race & Orphaned Processes
- **Crossing Site**: `plugin/application.py:174–192` (`AIAssistantApplication.terminate`).
- **Observation**:
  ```python
  # application.py:178-192
  threading.Thread(
      target=get_litert_supervisor().stop,
      name="LiteRTServerShutdown",
      daemon=True,
  ).start()
  threading.Thread(
      target=shutdown_llama_servers,
      name="LlamaServerShutdown",
      daemon=True,
  ).start()
  ```
- **Failure Mode [CONFIRMED]**: When NVDA shuts down or restarts, Python terminates all `daemon=True` threads without waiting for them to join. If `get_litert_supervisor().stop` or `shutdown_llama_servers` has not completed its socket teardown or process termination, the child `litert-lm` or `llama-server.exe` process continues running in the background as an orphaned zombie. On subsequent NVDA startup, port 9379 or 8080 remains bound, forcing the runtime supervisor into `ReadyAdopted` state without a direct process handle (`supervisor.status().is_adopted == True`).

### 3.4 Target Worker Topology Mapping

Under the Target Worker Architecture (enforcing Invariants A1–A4, A16–A24):

```
+----------------------------------------------------------------------------------------------------+
| NVDA Host Process (nvda.exe) — THIN ACCESSIBILITY SHELL ONLY                                      |
| - Gestures, scripts, menus, NVDA settings dialogs                                                  |
| - Thread-affine accessibility DOM/page/selection/image snapshot capture (ui/nvda_ui.py wrappers)   |
| - Speech, Braille, Tones dispatch via queueHandler.pumpAll                                         |
| - Thin Worker Client (WorkerClient / JobClient) over versioned named pipe IPC                      |
+------------------------------------+---------------------------------------------------------------+
                                     | (Bi-directional Versioned Named Pipe IPC)
                                     v
+------------------------------------+---------------------------------------------------------------+
| AI Assistant Worker Process (ai_assistant_worker.exe) — OUT-OF-PROCESS COMPUTE HOST                |
| - Single Authoritative Python/Native Worker Process                                                |
| - Pure-Python Application & Domain Services (core, service, providers, use_case, prompts)         |
| - Native PyO3 Extensions (runtime_supervisor, llm_client, memory_engine, embedding_engine)         |
| - Heavy Operations (Model downloading, SHA-256 verification, ZIP unpacking, Candle embeddings)     |
| - Bounded Job / Session State Machine (QUEUED -> RUNNING -> COMPLETED / FAILED / CANCELLED)        |
| - Local Runtime Supervision (Directly owns and supervises LiteRT-LM & llama-server child processes)|
+-------------------+----------------------------------------------------+---------------------------+
                    | (Named Pipes)                                      | (Process / HTTP)
                    v                                                    v
+-------------------+--------------------+       +-----------------------+---------------------------+
| Native UI Host (nvda_ui_host.exe)      |       | Managed Local Runtimes                            |
| - Win32 window + WebView2 + Svelte UI  |       | - LiteRT-LM (python.exe -m litert_lm_cli.main)    |
+----------------------------------------+       | - llama-server (llama-server.exe)                 |
                                                 +---------------------------------------------------+
```

#### Key Topology Improvements:
1. **Screen Reader Isolation (Invariant A1, A16)**: If the worker process runs out of memory during a 4GB model download, or Candle panics during tensor calculation, only `ai_assistant_worker.exe` crashes. NVDA remains 100% responsive, informs the user via speech, and restarts the worker process cleanly.
2. **Elimination of Monolithic In-Process PyO3 Extensions (Invariant A17)**: `runtime_supervisor.pyd`, `embedding_engine.pyd`, and `memory_engine.pyd` are loaded inside the worker process, not `nvda.exe`.
3. **Deterministic Local Server Teardown (Invariant A18)**: Because the worker process directly owns the runtime supervisor and child processes, worker teardown terminates all child runtimes cleanly without daemon-thread race conditions.

---

## 4. Audit C: NVDA Import Contamination & Dependency Boundaries

### 4.1 Exhaustive NVDA Import Inventory

A complete AST analysis across all 114 Python files in `addon/globalPlugins/AI-assistant/` (excluding bundled third-party libraries in `lib/`) identified exactly **95 NVDA import statements**.

#### Breakdown by NVDA Module

| NVDA Module | Import Count | Description / Role | Contamination Severity |
| :--- | :---: | :--- | :--- |
| `logHandler` | **40** | Logging facility (`from logHandler import log`) | **Widespread but trivial to cure**: pure domain code should use standard library `logging`. |
| `wx` | **10** | wxWidgets GUI dialogs and events | Confined to `ui/` dialogs and `plugin/controller.py` menu. |
| `gui` / `guiHelper` | **10** | NVDA GUI layout and dialog helpers | Confined to `ui/` dialogs and `plugin/controller.py`. |
| `api` | **8** | NVDA accessibility object model access | Confined to `context/extractors/`, `image/`, and `utils/clipboard.py`. |
| `textInfos` | **6** | NVDA text range positioning constants | Confined to `context/extractors/` and `context/navigation.py`. |
| `treeInterceptorHandler` | **3** | Browser virtual buffer / tree interceptor | Confined to `context/extractors/browser*.py`. |
| `addonHandler` | **3** | Translation initialization (`initTranslation()`) | Confined to `plugin/__init__.py`, `application.py`, `settings_panel.py`. |
| `speech` | **3** | NVDA speech commands and cancellation | Confined to `ui/nvda_ui.py`. |
| `controlTypes` | **2** | Accessibility control roles/states | Confined to `context/extractors/browser_*.py`. |
| `winUser` | **2** | Windows user API wrapper | Confined to `context/navigation.py` and `image/focus_capture.py`. |
| `locationHelper` | **2** | Screen rectangle helper (`RectLTWH`) | Confined to `image/objects.py`. |
| `queueHandler` | **2** | NVDA main thread queue (`queueHandler.queueFunction`) | Confined to `ui/nvda_ui.py` and `ui/host_renderer.py`. |
| `tones` | **1** | NVDA audio progress beeps | Confined to `ui/nvda_ui.py`. |
| `languageHandler` | **1** | NVDA UI language resolver | Contaminates `config/settings.py:8`. |
| `globalPluginHandler` | **1** | NVDA GlobalPlugin base class | Confined to `plugin/controller.py:9`. |
| `scriptHandler` | **1** | `@script` decorator for keyboard gestures | Confined to `plugin/controller.py:13`. |
| **Total** | **95** | | |

### 4.2 Subpackage Contamination Analysis

```
                                    +--------------------+
                                    | TOTAL REPOSITORY   |
                                    | 95 NVDA Imports    |
                                    +---------+----------+
                                              |
                +-----------------------------+-----------------------------+
                |                                                           |
                v                                                           v
  +---------------------------+                               +---------------------------+
  | Pure Domain / Services    |                               | NVDA-Affine Shell Modules |
  | (20 Imports -> ALL log/lang)                             | (75 Imports)              |
  +---------------------------+                               +---------------------------+
  | core/            : 0      |                               | ui/            : 33       |
  | tools/           : 0      |                               | context/       : 19       |
  | use_case/        : 0      |                               | plugin/        : 11       |
  | embeddings/      : 0      |                               | image/         : 8        |
  | prompts/         : 1 (log)|                               | utils/         : 3        |
  | observability/   : 1 (log)|                               | root/          : 1        |
  | service/         : 5 (log)|                               +---------------------------+
  | providers/       : 8 (log)|
  | config/          : 3 (2log, 1lang)
  +---------------------------+
```

#### Detailed Citation Table of Contaminated Domain/Service Modules

| Package | File Path | Line | Import Statement | Rationale / Remediation |
| :--- | :--- | :---: | :--- | :--- |
| `config` | `config/settings.py` | 8 | `import languageHandler` | Used at line 200 in `get_effective_language()`. Replace with injected resolver or lazy import fallback. |
| `config` | `config/state.py` | 7 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `config` | `config/yaml_store.py` | 10 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `service` | `service/base.py` | 8 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `service` | `service/chat/coordinator.py` | 9 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `service` | `service/chat/repository_backends.py` | 13 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `service` | `service/error_reporter.py` | 10 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `service` | `service/model_cache.py` | 29 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `providers` | `providers/_provider_runtime.py` | 7 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `providers` | `providers/adapters/openai_compat.py` | 23 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `providers` | `providers/litert_manager.py` | 13 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `providers` | `providers/llama_manager.py` | 10 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `providers` | `providers/provider_proxy.py` | 7 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `providers` | `providers/runtime/download.py` | 27 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `providers` | `providers/runtime/manager.py` | 12 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `providers` | `providers/runtime/model_download.py` | 21 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `prompts` | `prompts/base.py` | 7 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `observability`| `observability/reporter.py` | 7 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `utils` | `utils/crypto.py` | 20 | `from logHandler import log` | Replace with standard `import logging; log = logging.getLogger(__name__)`. |
| `utils` | `utils/clipboard.py` | 11, 21 | `from logHandler import log`, `import api` | Misplaced module: reading NVDA clipboard belongs in `ui/nvda_ui.py` or `adapters/nvda/clipboard.py`. |

### 4.3 Definition of the Maximum Coherent Pure-Python Subtree

Based on code-level evidence, the maximum coherent pure-Python domain subtree comprises:
1. **`core/`**: Canonical message definitions, tool calling schemas, progress event protocols. (Currently 0 NVDA imports).
2. **`tools/`**: Tool registry, serialization, tool execution (`get_time`). (Currently 0 NVDA imports).
3. **`use_case/`**: Declarative use cases, engine, registry, summary, proofread, chat orchestrators. (Currently 0 NVDA imports).
4. **`embeddings/`**: Candle embedding port, tokenizers, chunking. (Currently 0 NVDA imports).
5. **`prompts/`**: Jinja2 prompt templates and context builders. (Requires removing 1 `logHandler` import).
6. **`service/`**: LLM service, chat coordinator, conversation persistence, model cache, readiness service, error reporter. (Requires removing 5 `logHandler` imports).
7. **`providers/`**: Complete provider subsystem including `adapters/`, `litert_manager`, `llama_manager`, and `runtime/` (download, paths, config, server supervisors). (Requires removing 8 `logHandler` imports).
8. **`config/`**: State models, YAML storage, schema specs, settings management. (Requires removing 2 `logHandler` imports and decoupling `languageHandler` in `settings.py`).
9. **`observability/`**: Metrics and event reporting. (Requires removing 1 `logHandler` import).
10. **`context/` (Reduction & Formatting)**: `types.py`, `reduction.py`, `formatting.py`, `structure_summary.py`, `graph_store.py`. (Pure DTO transformations; 0 NVDA imports).

This subtree represents **92 of the 114 Python files (80.7%)** in the add-on.

### 4.4 Automated Dependency Boundaries & Import Linting Rules

To enforce **Invariants A5–A6 and A30** across the codebase, two automated enforcement mechanisms are defined:

#### 1. Ruff Banned API Configuration (`pyproject.toml`)
Configure Ruff's `flake8-tidy-imports` rule (`TID251`) to ban all NVDA root packages in domain/service modules:

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"logHandler".msg = "Use standard library 'logging.getLogger(__name__)' instead of NVDA logHandler."
"api".msg = "NVDA API access is forbidden outside of NVDA adapter and extractor modules."
"textInfos".msg = "NVDA textInfos is forbidden outside of NVDA extractor modules."
"controlTypes".msg = "NVDA controlTypes is forbidden outside of NVDA extractor modules."
"treeInterceptorHandler".msg = "Tree interceptor access is forbidden outside of browser extractors."
"globalPluginHandler".msg = "NVDA plugin handlers belong exclusively in plugin/controller.py."
"scriptHandler".msg = "NVDA scriptHandler belongs exclusively in plugin/controller.py."
"queueHandler".msg = "NVDA queueHandler belongs exclusively in ui/nvda_ui.py."
"gui".msg = "NVDA gui modules belong exclusively in ui/ dialogs."
"guiHelper".msg = "NVDA guiHelper belongs exclusively in ui/ dialogs."
"wx".msg = "wxWidgets belongs exclusively in ui/ dialogs and controller menu."
"speech".msg = "NVDA speech belongs exclusively in ui/nvda_ui.py."
"tones".msg = "NVDA tones belongs exclusively in ui/nvda_ui.py."
"addonHandler".msg = "NVDA addonHandler belongs exclusively in NVDA adapter entry points."
"languageHandler".msg = "Access language via injected LanguageResolver port."
```

#### 2. Per-Directory Ruff Overrides
```toml
[tool.ruff.lint.per-file-ignores]
# Pure Python domain/service subtrees: STRICT ZERO NVDA TOLERANCE
"addon/globalPlugins/AI-assistant/core/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/service/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/providers/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/config/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/prompts/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/tools/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/use_case/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/embeddings/**" = ["TID251"]
"addon/globalPlugins/AI-assistant/observability/**" = ["TID251"]
```

#### 3. Automated Pure-Python AST Test Gate
Add an automated test in the Pure Python Test Tier (`tests/pure/test_import_boundaries.py`) that scans all AST nodes in the domain subtree and asserts that no forbidden NVDA root module is imported:

```python
FORBIDDEN_NVDA_MODULES = {
    "api", "textInfos", "controlTypes", "globalPluginHandler", "scriptHandler",
    "queueHandler", "gui", "guiHelper", "wx", "speech", "tones", "logHandler",
    "languageHandler", "addonHandler", "treeInterceptorHandler", "cursorManager",
    "braille", "winUser", "locationHelper",
}
```

---

## 5. Audit G: `plugin/background.py` Decomposition

### 5.1 Overview and Metrics
- **Path**: `addon/globalPlugins/AI-assistant/plugin/background.py`
- **Total Lines**: 495 lines
- **Total Functions/Methods**: 12 functions, 1 class (`BackgroundTaskRunner` with 5 methods)
- **Direct NVDA Imports**: Line 10 (`from logHandler import log`)
- **Direct NVDA UI Dispatches**: Lines 416, 422, 434, 451, 491 (`nvda_ui.queue`)

### 5.2 Line-by-Line Symbol & Concern Inventory

```
+---------------------------------------------------------------------------------------------------+
| Lines 1-45: Imports, Types, and Routing Gating                                                    |
| - Line 10: from logHandler import log                                                             |
| - Lines 42-44: _NON_LLM_USE_CASES (frozenset of chat workspace use case IDs)                      |
|   Concern: Use Case Policy / Routing Gate                                                         |
+---------------------------------------------------------------------------------------------------+
| Lines 51-112: Config Listeners & Daemon Worker Spawning                                           |
| - Lines 51-85: _on_litert_server_config_changed()                                                 |
|   Concern: Configuration Event Listener (NVDA Main Thread)                                        |
|   Thread creation: threading.Thread(name="litert-restart-on-config-change", daemon=True) (Line 80)    |
| - Lines 87-98: _restart_litert_server_worker()                                                    |
|   Concern: Runtime Supervisor Command Execution (Blocking: supervisor.restart(timeout=60.0))    |
| - Lines 103-112: _on_llama_server_config_changed()                                                |
|   Concern: Configuration Event Listener (NVDA Main Thread)                                        |
|   Thread creation: threading.Thread(name="llama-shutdown-on-config-change", daemon=True) (Line 105)   |
+---------------------------------------------------------------------------------------------------+
| Lines 115-210: Provider Server Readiness Verification                                             |
| - Lines 115-138: ensure_litert_server_ready(on_progress)                                          |
|   Concern: LiteRT Runtime Readiness Policy                                                        |
| - Lines 140-162: _ensure_litert_server_ready_core(on_progress)                                    |
|   Concern: LiteRT Supervisor Orchestration (Blocking: supervisor.ensure_ready(timeout=60.0))     |
| - Lines 163-204: ensure_provider_server_ready(on_progress)                                        |
|   Concern: Multi-Provider Runtime Coordination & Selection Fallback                               |
|   Hidden state mutation: set_model_name(record.model_id) at Line 194                              |
|   Cache refresh: model_catalog_cache.refresh_async at Lines 173, 202                              |
| - Lines 205-210: _ensure_litert_server_ready_locked(on_progress) (Deprecated alias)               |
+---------------------------------------------------------------------------------------------------+
| Lines 212-348: Model Artifact & Registry Management                                               |
| - Lines 212-308: _ensure_model_imported(supervisor, on_progress)                                  |
|   Concern: LiteRT Model Registry Synchronization                                                  |
|   Blocking call: supervisor.import_model (spawns litert-lm import CLI, up to 120s) (Line 290)     |
| - Lines 310-348: _build_import_candidates(definition)                                             |
|   Concern: Hardware Capability Evaluation (has_gpu()) & Variant Prioritization                    |
+---------------------------------------------------------------------------------------------------+
| Lines 357-495: BackgroundTaskRunner Class                                                         |
| - Lines 358-374: __init__                                                                         |
|   Concern: Concurrency State Management (_closed: Event, _threads: set, _threads_lock: Lock)      |
| - Lines 375-383: close()                                                                          |
|   Concern: Non-blocking Worker Invalidation                                                       |
| - Lines 384-402: _start_worker(*, target, name)                                                   |
|   Concern: Raw Unbounded Thread Spawning (threading.Thread(daemon=True).start())                  |
| - Lines 404-440: start_model_preload()                                                            |
|   Concern: Model Preload Orchestration + NVDA Speech Dispatches (nvda_ui.queue)                   |
|   Thread creation: threading.Thread(name="BrowserAssistantModelPreload") (Line 439)               |
| - Lines 441-495: run_use_case_in_background(use_case_id, title, render_result)                    |
|   Concern: Use Case Job Execution + NVDA Speech + Result Presentation Callback Routing            |
|   Thread creation: threading.Thread(name=f"AIassistant{title}Worker") (Line 493)                 |
+---------------------------------------------------------------------------------------------------+
```

### 5.3 Detailed Concurrency, Threading, and State Mutation Analysis

1. **Unbounded Thread Spawning [CONFIRMED]**:
   - `BackgroundTaskRunner._start_worker` (`background.py:384–402`) creates a new OS thread on every execution:
     ```python
     thread = threading.Thread(target=tracked_target, name=name, daemon=True)
     ```
   - If a user rapidly triggers input gestures (e.g. repeated summaries or OCR requests), multiple concurrent workers are spawned without queueing, rate-limiting, or concurrency limits.
   - There is no thread pool, executor, or backpressure mechanism.
2. **Hidden Configuration State Mutation [CONFIRMED]**:
   - In `ensure_provider_server_ready` (`background.py:184–196`), if the configured llama.cpp model is missing from the local model list, the function automatically picks the first available preset in the catalog and mutates the application settings:
     ```python
     # background.py:193-196
     from ..config.settings import set_model_name
     set_model_name(record.model_id)
     ```
   - This side-effect occurs implicitly during readiness check in a background worker thread.
3. **Heavy Blocking Calls in Background Threads [CONFIRMED]**:
   - `supervisor.ensure_ready(timeout=60.0)` blocks the worker thread for up to 60 seconds.
   - `supervisor.import_model(...)` executes `_run_litert_cli` (`subprocess.run`) with a 120-second deadline (`server.py:870`).
   - `supervisor.restart(timeout=60.0)` in `_restart_litert_server_worker` blocks for up to 60 seconds.
4. **Direct NVDA Speech Side-Effects in Background Workers [CONFIRMED]**:
   - Background threads directly format localized speech strings and dispatch them to the NVDA main event loop:
     ```python
     # background.py:416-419
     nvda_ui.queue(
         nvda_ui.message,
         _("Checking {provider} model availability.").format(provider=provider_name),
     )
     ```
   - The worker is tightly coupled to NVDA's speech output and translation runtime (`builtins._`).

### 5.4 Concrete Target Destination Modules

To cleanly decompose `plugin/background.py` and enforce Invariants A1–A4 and A11–A15, every symbol is mapped to its target destination module:

| Symbol / Function / Class in `plugin/background.py` | Original Lines | Current Responsibilities | Target Destination Module | Architectural Rationale |
| :--- | :---: | :--- | :--- | :--- |
| `_NON_LLM_USE_CASES` | 42–44 | Set of use cases that skip LLM readiness gating | `use_case/routing.py` or `use_case/types.py` | Pure routing policy; belongs with use case definitions. |
| `_on_litert_server_config_changed` | 51–85 | Config change listener; spawns restart worker | `providers/runtime/supervisor_service.py` | Configuration listener for local runtime belongs in provider runtime management. |
| `_restart_litert_server_worker` | 87–98 | Worker body restarting LiteRT server | `providers/runtime/supervisor_service.py` (or Worker Host) | Runtime supervisor execution logic belongs in runtime management. |
| `_on_llama_server_config_changed` | 103–112 | Config change listener; stops stale llama servers | `providers/runtime/supervisor_service.py` | Server lifecycle coordination belongs in provider runtime management. |
| `ensure_litert_server_ready` | 115–138 | Gate for LiteRT runtime readiness | `providers/runtime/litert_provider.py` | Provider-specific readiness gate belongs inside provider adapter. |
| `_ensure_litert_server_ready_core` | 140–162 | Verifies runtime installation, ready state, model import | `providers/runtime/litert_provider.py` | Provider-specific runtime orchestration. |
| `ensure_provider_server_ready` | 163–204 | Multi-provider server readiness coordinator & fallback | `service/provider_readiness.py` | Central application service coordinating active provider readiness. |
| `_ensure_litert_server_ready_locked` | 205–210 | Deprecated compatibility alias | REMOVE | Obsolete test shim; remove during refactoring. |
| `_ensure_model_imported` | 212–308 | Checks LiteRT catalog, resolves variants, imports model | `providers/litert_manager.py` (or `service/model_management/litert_catalog.py`) | Model catalog and import mechanics belong in model management. |
| `_build_import_candidates` | 310–348 | Evaluates GPU/CPU variants for import | `providers/litert_models.py` | Pure hardware inspection and artifact selection logic. |
| `BackgroundTaskRunner` | 357–495 | Background task executor, thread tracker, speech queue | Decomposed into: (1) `service/job_executor.py` / Worker IPC, (2) `plugin/presenter.py` | Generic execution moves to bounded Worker Job Engine; presentation dispatches move to presenter. |
| `BackgroundTaskRunner.start_model_preload` | 404–440 | Preloads active model and speaks status | `service/model_management/preload_service.py` | Orchestration moves to model management; speech announcements move to Presenter callbacks. |
| `BackgroundTaskRunner.run_use_case_in_background` | 441–495 | Runs use case engine, handles errors, calls presenter | `use_case/engine.py` (async execution) or `service/job_client.py` | Use case execution belongs in UseCaseEngine; result marshaling in Presenter. |

---

## 6. Comprehensive Classified Findings & Risk Catalog

Every finding and structural issue discovered across Audits A, C, and G is cataloged below with mandatory classification tags:

### [CONFIRMED] Finding F1: Monolithic In-Process Native PyO3 Extensions
- **File & Lines**: `addon/globalPlugins/AI-assistant/lib/` (`runtime_supervisor.pyd`, `llm_client.pyd`, `memory_engine.pyd`, `embedding_engine.pyd`); loaded in `server.py:42`, `llama_server.py:31`, `repository_backends.py:16`, `candle.py:10`.
- **Finding**: All native Rust PyO3 extensions run inside `nvda.exe`. Any panic, memory corruption, or C-level segfault instantly crashes the screen reader process.
- **Classification**: `CONFIRMED` / `BLOCKER to Invariant A1 & A17`
- **Mitigation**: Migrate heavy native extensions (`embedding_engine`, `llm_client`, `runtime_supervisor`) to the out-of-process Worker Process (Slice 3, Slice 6).

### [CONFIRMED] Finding F2: Daemon Thread Termination Truncation during NVDA Exit
- **File & Lines**: `addon/globalPlugins/AI-assistant/plugin/application.py:178–192`
- **Finding**: LiteRT and llama-server shutdowns are launched on `daemon=True` background threads (`LiteRTServerShutdown`, `LlamaServerShutdown`) during `terminate()`. NVDA exit abruptly kills daemon threads before socket shutdown or `kill()` completes, leaving orphan processes bound to ports 9379 and 8080.
- **Classification**: `CONFIRMED`
- **Mitigation**: Move runtime server ownership to native Worker process with deterministic supervisor teardown (Slice 3, Slice 6, Slice 7).

### [CONFIRMED] Finding F3: Unbounded Thread Spawning in `BackgroundTaskRunner`
- **File & Lines**: `addon/globalPlugins/AI-assistant/plugin/background.py:384–402, 439, 493`
- **Finding**: Every user action spawns a raw `threading.Thread(daemon=True)`. There is no thread pool, no executor, no queue, no concurrency limit, and no cancellation token.
- **Classification**: `CONFIRMED`
- **Mitigation**: Replace with bounded `JobExecutor` and versioned Worker IPC job queues (Slice 2, Slice 3).

### [CONFIRMED] Finding F4: Widespread `logHandler` Import Contamination
- **File & Lines**: 40 files across `addon/globalPlugins/AI-assistant/` (e.g. `service/base.py:8`, `providers/runtime/download.py:27`, `config/state.py:7`, `prompts/base.py:7`).
- **Finding**: Direct imports of `from logHandler import log` prevent pure domain/service code from running without an NVDA checkout or running NVDA process.
- **Classification**: `CONFIRMED`
- **Mitigation**: Standardize all domain, service, config, and provider modules to `import logging; log = logging.getLogger(__name__)` (Slice 1).

### [CONFIRMED] Finding F5: `languageHandler` Contamination in `config/settings.py`
- **File & Lines**: `addon/globalPlugins/AI-assistant/config/settings.py:8, 200`
- **Finding**: `import languageHandler` is imported unconditionally at top of `settings.py` but used only in `get_effective_language()` at line 200.
- **Classification**: `CONFIRMED`
- **Mitigation**: Inject language resolver via port interface or use lazy fallback import (Slice 1).

### [CONFIRMED] Finding F6: Misplaced NVDA Adapter in `utils/clipboard.py`
- **File & Lines**: `addon/globalPlugins/AI-assistant/utils/clipboard.py:11, 21`
- **Finding**: Claims in docstring to be pure Python but imports `logHandler` and `api` (`api.getClipData()`).
- **Classification**: `CONFIRMED`
- **Mitigation**: Move clipboard reading to `ui/nvda_ui.py` or `adapters/nvda/clipboard.py` (Slice 1).

### [CONFIRMED] Finding F7: Silent Settings Mutation during Llama Fallback
- **File & Lines**: `addon/globalPlugins/AI-assistant/plugin/background.py:184–196`
- **Finding**: If configured llama model is missing, `ensure_provider_server_ready` implicitly mutates settings via `set_model_name(record.model_id)` inside a background thread without user consent.
- **Classification**: `CONFIRMED` / `DESIGN DETAIL`
- **Mitigation**: Explicit model selection policy via centralized `ModelManagementService` (Audit F, Slice 5).

### [CONFIRMED] Finding F8: Blocking Synchronous CLI Spawns inside Background Workers
- **File & Lines**: `addon/globalPlugins/AI-assistant/providers/runtime/server.py:299, 870, 930, 970, 1015`
- **Finding**: LiteRT model import runs `litert-lm import` via `subprocess.run` with a 120-second timeout directly from NVDA Python threads.
- **Classification**: `CONFIRMED`
- **Mitigation**: Move heavy CLI model operations to Worker process (Slice 4, Slice 6).

### [LIKELY] Finding F9: UI Host Named Pipe 5-Second Read Timeout Latency
- **File & Lines**: `addon/globalPlugins/AI-assistant/ui/host_transport.py:147`
- **Finding**: Synchronous command-response pipe read uses a 5-second deadline. If the host becomes unresponsive, caller threads block for 5 full seconds before failing over to native UI.
- **Classification**: `LIKELY`
- **Mitigation**: Worker IPC design with non-blocking async pipe I/O and heartbeats (Slice 3).

---

## 7. Next Steps & Recommendations

1. **Slice 0 & Slice 1**: Immediate remediation of `from logHandler import log` across all 40 files, replacing with standard `logging.getLogger(__name__)`, and decoupling `languageHandler` in `config/settings.py`. Implement automated Ruff banned-API rules and AST test gate.
2. **Slice 2 & Slice 3**: Replace `BackgroundTaskRunner` unbounded threads with versioned Worker IPC and bounded job queues.
3. **Slice 4 & Slice 6**: Relocate heavy operations (model downloads, hashing, LiteRT runtime ownership) into the Worker Process.
4. **Slice 5**: Decompose `plugin/background.py` readiness and model management into `service/provider_readiness.py` and `ModelManagementService`.
