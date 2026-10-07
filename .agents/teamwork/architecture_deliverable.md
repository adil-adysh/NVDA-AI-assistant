# NVDA AI Assistant — Pre-Implementation Architectural Deliverable & Target Slices 0–10 Implementation Plan

**Document Version:** 1.0.0 (Authoritative Master Synthesis)  
**Date:** 2026-10-03  
**Repository:** `adil-adysh/NVDA-AI-assistant`  
**Baseline Git Commit:** `ced1cbc` (and ancestors)  
**Lead Author & Synthesizer:** Architecture Synthesizer & Lead Technical Author (Agent 8)  
**Contributing Audit Teams:**  
- Current Architecture & Process Topology Auditor (Agent 1: Audits A, C, G)  
- NVDA Boundary & Thread-Affinity Auditor (Agent 2: Audit B, Invariants A1–A4, A27)  
- Rust Runtime & Concurrency Auditor (Agent 3: Audit E, Invariants A7–A10, A25–A26)  
- Pure-Python & Test Architect (Agent 4: Audit D, Invariants A5–A6, A30)  
- Model-Management Architect (Agent 5: Audit F, Invariants A11–A15)  
- Worker / Job / IPC Implementation Designer (Agent 6: Invariants A16–A24, A29, Slices 2–4, 9–10)  
**Mandatory Invariants Enforced:** Invariants A1–A30  
**Mandatory Finding Classifications:** `CONFIRMED`, `LIKELY`, `DESIGN DETAIL`, `BLOCKER`, `UNKNOWN / REQUIRES EXPERIMENT`  

---

## Executive Summary & Integrity Attestation

This document constitutes the definitive, evidence-driven pre-implementation architectural specification for `NVDA-AI-assistant`. It synthesizes all architectural, dependency, thread-affinity, native runtime, test-tier, model management, and IPC audits conducted across the repository at commit `ced1cbc`.

NVDA is an essential assistive technology for blind and vision-impaired users. The primary architectural imperative of this add-on is absolute isolation of NVDA's accessibility event loop:
1. **Screen Reader Survival**: Any native crash (segfault, memory fault, driver crash, CUDA abort) in local AI runtimes or deep-learning extensions must never crash `nvda.exe`.
2. **Sub-50ms Event Loop Responsiveness**: The NVDA main thread must never execute blocking socket I/O, sleep loops, heavy CPU bitmap compression, full-DOM traversal, or unmanaged thread synchronization.
3. **Pure-Python Domain Isolation**: 80%+ of the codebase is decoupled into a pure-Python domain/service layer capable of fast (< 3s) testing without a running NVDA instance or sibling checkout.
4. **Authoritative Worker Topology**: All heavy compute, model downloading, local server supervision, and continuous streaming (OCR, Transcription) are migrated into an out-of-process, supervised Worker process (`ai_assistant_worker.exe`) protected by a Windows Job Object.

All code citations in this document reference exact file paths and line numbers from HEAD (`ced1cbc`). All findings and risks are strictly classified according to the mandatory taxonomy.

---

## Table of Contents

1. [Current Process Topology](#1-current-process-topology)
2. [Target Process Topology](#2-target-process-topology)
3. [Current Dependency Graph](#3-current-dependency-graph)
4. [Target Dependency Graph](#4-target-dependency-graph)
5. [Complete Thread & Executor Map](#5-complete-thread--executor-map)
6. [NVDA Import Map & Boundary Enforcement](#6-nvda-import-map--boundary-enforcement)
7. [Test-Tier Redesign](#7-test-tier-redesign)
8. [Rust Supervisor Audit & Findings](#8-rust-supervisor-audit--findings)
9. [LiteRT Flow Architecture](#9-litert-flow-architecture)
10. [llama.cpp Flow Architecture](#10-llamacpp-flow-architecture)
11. [Current Model Responsibility Map](#11-current-model-responsibility-map)
12. [Target Model-Management Decomposition](#12-target-model-management-decomposition)
13. [Current Background-Task Map](#13-current-background-task-map)
14. [Worker IPC Architecture (Versioning, Handshake, Protocol)](#14-worker-ipc-architecture-versioning-handshake-protocol)
15. [Job & Session State Model](#15-job--session-state-model)
16. [Immutable DTO Definitions & Schemas](#16-immutable-dto-definitions--schemas)
17. [Migration Slices (Slices 0–10 Implementation Plans)](#17-migration-slices-slices-010-implementation-plans)
18. [Acceptance Tests per Slice](#18-acceptance-tests-per-slice)
19. [Rollback Points & Reversibility](#19-rollback-points--reversibility)
20. [Packaging Implications (.nvda-addon, SCons, Wheels)](#20-packaging-implications-nvda-addon-scons-wheels)
21. [Worker & Runtime Recovery Strategy](#21-worker--runtime-recovery-strategy)
22. [Accessibility Impact & Responsiveness Guarantees](#22-accessibility-impact--responsiveness-guarantees)
23. [Performance & Resource Limits](#23-performance--resource-limits)
24. [Master Catalog of Risks, Blockers & Classified Findings](#24-master-catalog-of-risks-blockers--classified-findings)

---

## 1. Current Process Topology

### 1.1 Process Inventory at HEAD (`ced1cbc`)

At commit `ced1cbc`, the application runtime spans six distinct process categories, four in-process native shared libraries, and multiple unmanaged subprocesses:

```
+----------------------------------------------------------------------------------------------------+
| 1. NVDA Host Process (nvda.exe) [PID: N]                                                           |
|    - Main Event Loop Thread (queueHandler.pumpAll, wx.App main loop)                               |
|    - Python Global Plugin Runtime (addon/globalPlugins/AI-assistant/)                              |
|    - Monolithic In-Process PyO3 Extensions (runtime_supervisor, llm_client, memory_engine, Candle) |
|    - 15+ Unmanaged Python Daemon Threads (BackgroundTaskRunner, ModelListFetch, etc.)             |
+------------------------------------+--------------------------------+------------------------------+
                                     | (Named Pipes)                  | (std::process::Command)
                                     v                                v
+------------------------------------+-----------+    +---------------+------------------------------+
| 2. UI Host Process (nvda_ui_host.exe) [PID: H] |    | 5. Managed LiteRT-LM Server Process [PID: L] |
|    - Native Win32 Window Message Loop          |    |    (python.exe -m litert_lm_cli.main serve)  |
|    - Windows Named Pipe Server (cmd & evt)     |    |    - HTTP API: http://127.0.0.1:9379/        |
|    +-----------------------------------------+ |    +----------------------------------------------+
|    | 3. WebView2 Subprocesses                | |                                                   |
|    |    (msedgewebview2.exe x N)             | |    +----------------------------------------------+
|    |    - Chromium GPU/Renderer/Utility      | |    | 6. Managed llama-server Process [PID: M]     |
|    |    - Svelte 5 Web UI Runtime            | |    |    (llama-server.exe)                        |
|    +-----------------------------------------+ |    |    - HTTP API: http://127.0.0.1:8080/        |
+------------------------------------------------+    +----------------------------------------------+
                                                                      | (subprocess.run)
                                                                      v
                                                      +---------------+------------------------------+
                                                      | 7. Ephemeral Subprocesses                    |
                                                      |    - litert-lm import, list, dir, remove     |
                                                      +----------------------------------------------+
```

### 1.2 Process Attribute Matrix

| Process / Component | Creation Site & Mechanism | Ownership & Supervision | Transport / IPC | Health Check Mechanism | Restart Policy | Teardown Sequence | Failure Isolation | Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. NVDA Host Process (`nvda.exe`)** | OS shell launch. Hosts CPython interpreter. | User interactive desktop session. | Win32 messages, COM/UIA hooks, `queueHandler`. | Windows OS watchdog timer. | If NVDA crashes, speech and braille terminate instantly. | `GlobalPlugin.terminate()` (`controller.py:74`). | **ZERO isolation**: any fatal native error terminates screen reader. | `CONFIRMED` |
| **2. Python Global Plugin Runtime** | `globalPluginHandler.loadPlugins()` in `nvda.exe`. | In-process module tree under `AI-assistant/`. | Python call stack, `nvda_ui.queue` to main thread. | None. Unhandled thread errors logged to `error_reporter`. | Recreated on NVDA plugin reload (`NVDA+Q` or `NVDA+F3`). | `GlobalPlugin.terminate()` -> `AIAssistantApplication.terminate()`. | Shared with `nvda.exe`: GIL contention and C-level segfaults kill NVDA. | `CONFIRMED` |
| **3. UI Host (`nvda_ui_host.exe`)** | `ui/host_process.py:86` via `subprocess.Popen([host_exe], creationflags=CREATE_NEW_PROCESS_GROUP)`. | Module-level global `_host_process` (`host_process.py:14`), guarded by `_process_lock`. | 2 Named Pipes (`\\.\pipe\nvda_ai_assistant_ui_cmd`, `\\.\pipe\nvda_ai_assistant_ui_evt`), stdout pipe. | `WaitNamedPipe` probe (`host_process.py:54`); `UiCommand::HealthCheck`; `process.poll()`. | On pipe failure or crash, `ui/adapter.py` falls back to native NVDA dialogs. Restarted on next UI request. | `ui/host_process.py:134` (`stop_host()`): `process.terminate()`, wait 5s, then `kill()`. | **High**: Host crash does not crash NVDA. Python catches pipe errors and falls back. | `CONFIRMED` |
| **4. WebView2 Subprocesses (`msedgewebview2.exe`)** | Spawned internally by WebView2 COM loader in `nvda_ui_host.exe`. | Child processes of `nvda_ui_host.exe` (Chromium multi-process architecture). | Chromium IPC; JS bridge `window.chrome.webview.postMessage` / `__receiveHostCommand`. | Chromium internal crash handler; `CoreWebView2ProcessFailed` handler in Rust host. | Recreated by WebView2 runtime or host window reload. | Terminated automatically when `nvda_ui_host.exe` exits. | **High**: Render process crash does not crash `nvda.exe`. Host logs error. | `DESIGN DETAIL` |
| **5. LiteRT-LM Server Process** | Rust `runtime_supervisor::process::OsProcessDriver` (`process.rs:48`) via `Command::spawn`, or Python fallback `server.py:309`. | Native `RuntimeSupervisor` instance inside `nvda.exe` via `LiteRTServerSupervisor`. | HTTP / SSE over `http://127.0.0.1:9379/` (`/v1/models`, `/v1/chat/completions`). | Polling `GET /v1/models` every 500ms via `UreqHealthChecker` (`health.rs:12`) up to 60s; `process.poll()`. | Replaced if startup configuration snapshot changes (`server.py:666`); `restart()` invokes `stop()` then `ensure_ready()`. | `plugin/application.py:178` launches `Thread(target=supervisor.stop, name="LiteRTServerShutdown", daemon=True)`. | **Moderate**: Server crash raises `LiteRTServerError`. But daemon thread shutdown on NVDA exit risks orphaned process. | `CONFIRMED` |
| **6. llama-server Process (`llama-server.exe`)** | Rust `runtime_supervisor::process::OsProcessDriver` or Python `subprocess.Popen` in `llama_server.py:170`. | Native `RuntimeSupervisor` instance inside `nvda.exe` via `LlamaServerSupervisor`. | HTTP / SSE over `http://127.0.0.1:8080/` (`/v1/chat/completions`, `/models`). | Polling `GET /v1/models` or `/models` via `UreqHealthChecker`; child exit detection. | Replaced when startup configuration (model, threads, ctx) changes (`llama_server.py:326`). | `plugin/application.py:186` launches `Thread(target=shutdown_llama_servers, name="LlamaServerShutdown", daemon=True)`. | **Moderate**: Isolated OS process. However, daemon thread shutdown risks orphaned process. | `CONFIRMED` |
| **7. In-Process Native PyO3 Extensions** | Dynamically loaded `.pyd` libraries in `lib/`: `runtime_supervisor`, `llm_client`, `memory_engine`, `embedding_engine`. | Injected into `nvda.exe` CPython address space. | Direct C-ABI Python FFI / PyO3 calls. | None (in-process native code). | Cannot be unloaded or restarted without restarting `nvda.exe`. | Unloaded when `nvda.exe` exits. | **ZERO isolation**: Native panic or memory fault directly crashes `nvda.exe`. | `CONFIRMED` |
| **8. Ephemeral Subprocesses** | `providers/runtime/server.py:299` via `subprocess.run(cmd, timeout=...)` for CLI operations (`import`, `list`, `dir`). | Ephemeral child processes spawned from NVDA threads. | Standard pipes (`stdout=PIPE, stderr=PIPE`). | Process returncode and `TimeoutExpired` handling. | Retried on subsequent user actions. | Terminated upon command completion or timeout expiry. | Blocks background thread for up to 120s (`server.py:870`). | `CONFIRMED` |

### 1.3 Critical Architectural Deficiencies Identified in Current Topology

1. **Native Extension Monolith (Invariant A1, A16 Violation) [CONFIRMED, BLOCKER]**:
   All four native Rust extensions (`runtime_supervisor.pyd`, `embedding_engine.pyd`, `llm_client.pyd`, `memory_engine.pyd`) run inside `nvda.exe` (`server.py:42`, `llama_server.py:31`, `repository_backends.py:16`, `candle.py:10`). Running Candle deep-learning tensor calculations and SQLite/redb storage inside the screen reader exposes `nvda.exe` to native out-of-memory aborts and C-level crashes.
2. **Daemon Thread Truncation & Orphaned Process Leaks [CONFIRMED, BLOCKER]**:
   In `plugin/application.py:178–192`, server shutdowns are launched on `daemon=True` threads (`LiteRTServerShutdown`, `LlamaServerShutdown`). When NVDA restarts or exits, Python terminates daemon threads instantly without waiting for `stop()` or process termination to complete. The child `litert-lm` or `llama-server.exe` continues running as an orphaned zombie holding ports 9379/8080 and GPU VRAM.
3. **Synchronous 5-Second Pipe Read Blocks [CONFIRMED, LIKELY]**:
   `ui/host_transport.py:147` uses a blocking 5.0-second read deadline over `\\.\pipe\nvda_ai_assistant_ui_cmd`. While isolated from NVDA's main thread by `UIAdapter._worker_thread`, any stalled pipe operation blocks the adapter worker queue for 5 seconds.

---

## 2. Target Process Topology

### 2.1 Target Process Architecture (Invariants A1, A16–A20, A25)

The target architecture enforces a clean separation of concerns into three authoritative processes:

```
+----------------------------------------------------------------------------------------------------+
| 1. NVDA Host Process (nvda.exe) — THIN ACCESSIBILITY SHELL ONLY                                    |
|    - Gestures, scripts, menus, NVDA settings dialogs                                               |
|    - Thread-affine accessibility DOM/page/selection/image snapshot capture (ui/nvda_ui.py)         |
|    - Speech, Braille, Tones dispatch via queueHandler.pumpAll                                      |
|    - UI Transport Client to nvda_ui_host.exe                                                       |
|    - Worker Client (WorkerClient / JobClient) over versioned named pipe IPC                        |
+------------------------------------+-------------------------------+-------------------------------+
                                     | (Named Pipes)                 | (Named Pipes)
                                     | \\.\pipe\nvda_worker_cmd      | \\.\pipe\nvda_ui_cmd
                                     | \\.\pipe\nvda_worker_evt      | \\.\pipe\nvda_ui_evt
                                     v                               v
+------------------------------------+--------------------------+    +-------------------------------+
| 2. AI Assistant Worker Process (ai_assistant_worker.exe)     |    | 3. Native UI Host Process     |
|    - Out-of-Process Native & Python Compute Host              |    |    (nvda_ui_host.exe)         |
|    - Wrapped in Windows Job Object (KILL_ON_JOB_CLOSE)        |    |    - Native Win32 Window Loop |
|    - Bounded Job & Session State Machines (Discrete & Streams)|    |    - WebView2 + Svelte 5 UI   |
|    - Heavy Compute: Model Downloads, SHA-256, ZIP Extraction  |    +-------------------------------+
|    - In-Process PyO3 Extensions (runtime_supervisor, Candle)  |
|    - Centralized ModelManagementService Engine                |
|    - Authoritative Owner of Local Server Processes            |
+--------------------+------------------------------------------+
                     | (std::process::Command under Job Object)
                     +------------------------------------------+
                     |                                          |
                     v                                          v
+--------------------+---------------------+    +---------------+-------------------------------+
| 4. Managed LiteRT-LM Server Process      |    | 5. Managed llama-server Process               |
|    (python.exe -m litert_lm_cli.main)    |    |    (llama-server.exe)                         |
|    - HTTP API: http://127.0.0.1:9379/    |    |    - HTTP API: http://127.0.0.1:8080/         |
+------------------------------------------+    +-----------------------------------------------+
```

### 2.2 Target Process Attribute & Supervision Matrix

| Component | Host Boundary | Ownership / Supervision | IPC Transport | Failure Isolation | Invariant Enforced |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NVDA Shell** | `nvda.exe` | User Desktop Session | Win32 Accessibility Hooks | Isolated from compute crashes | **A1, A2, A3, A4** |
| **Worker Process** | `ai_assistant_worker.exe` (or worker subprocess) | Supervised by NVDA via `WorkerSupervisor` + Windows Job Object | Duplex Named Pipes (`cmd`, `evt`) with NDJSON & binary framing | Crash drops pipe; NVDA restarts worker cleanly; screen reader survives | **A16, A17, A18, A19, A20** |
| **UI Host** | `nvda_ui_host.exe` | Supervised by NVDA via `UIAdapter` + `_host_process` | Duplex Named Pipes (`ui_cmd`, `ui_evt`) | Host crash falls back to native NVDA dialogs | **A1, A27** |
| **Local Runtimes** | `litert-lm`, `llama-server.exe` | Supervised authoritatively by Worker Process via `runtime_supervisor` | HTTP / SSE loopback | Contained within Worker Job Object; zero NVDA process leakage | **A7, A8, A9, A25, A26** |

### 2.3 Windows Job Object Guarantees (Invariant A16, A26)

To completely eliminate orphaned processes and memory leaks on abnormal termination:
1. NVDA creates an anonymous Win32 Job Object (`CreateJobObjectW`) upon initializing `WorkerSupervisor`.
2. The Job Object is configured with `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` setting:
   - `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: If `nvda.exe` exits or is terminated via Task Manager, the Windows kernel automatically terminates `ai_assistant_worker.exe` and all child processes (`llama-server.exe`, `litert-lm`).
   - `JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION`: Prevents modal Win32 Watson/WER crash dialogs from blocking process cleanup.
3. The Worker process assigns any spawned runtime child processes to the same Job Object.

---

## 3. Current Dependency Graph

### 3.1 Intra-Package Architecture at HEAD (`ced1cbc`)

Across the 114 production Python files in `addon/globalPlugins/AI-assistant/`:

```
[NVDA Core Runtime: api, gui, wx, queueHandler, logHandler, languageHandler]
     |
     +------------+-------------------------+----------------------+
     |            |                         |                      |
     v            v                         v                      v
[plugin/controller.py]                [ui/nvda_ui.py]     [config/settings.py] (languageHandler:8)
     |                                      |                      |
     v                                      v                      v
[plugin/application.py] <-------------- [ui/adapter.py]   [config/state.py] (logHandler:7)
     |                                      |                      |
     +-------------------+                  v                      v
     |                   |          [ui/host_transport]   [config/model_config.py]
     v                   v                  |                      |
[plugin/background.py] [plugin/presenter.py]|                      |
     |                   |                  v                      |
     |                   +------------> [nvda_ui_host.exe]         |
     |                                                             |
     v                                                             v
[service/provider_readiness.py] <------------------------- [service/model_cache.py]
     |                                                             |
     v                                                             v
[providers/runtime/manager.py] <-------------------------- [providers/litert_manager.py]
     |                                                             |
     v                                                             v
[providers/runtime/server.py] <--------------------------- [providers/llama_manager.py]
     |                                                             |
     v                                                             v
[runtime_supervisor.pyd (in-process)]                   [embedding_engine.pyd (in-process)]
```

### 3.2 Key Coupling Flaws at HEAD

1. **`plugin/background.py` Central Hub Anti-Pattern**: Conflates use-case execution, local runtime startup, CLI subprocess execution, NVDA speech output, and hardware inspection into a 495-line monolith.
2. **Top-Level Package Name Collision with NVDA**: The add-on directories `config/`, `core/`, `ui/`, and `utils/` directly shadow NVDA's top-level source modules (`config`, `core.py`, `ui`, `utils`). This forces the synthetic dynamic loader boilerplate in `tests/support/bootstrap.py`.
3. **`logHandler` Contamination**: 40 files across domain, service, provider, and config packages directly import `from logHandler import log`, blocking pure-Python execution.

---

## 4. Target Dependency Graph

### 4.1 Layered Target Architecture (Invariants A5–A6, A30)

The target architecture establishes strict dependency inversion where inner domain and service layers have zero knowledge of NVDA or outer presentation adapters:

```
+---------------------------------------------------------------------------------------------------+
| LAYER 0: NVDA SHELL & ACCESSIBILITY ADAPTERS                                                       |
| - plugin/controller.py (GlobalPlugin, scripts, gestures)                                          |
| - ui/nvda_ui.py (queueHandler, speech, tones, main thread call/queue)                             |
| - context/extractors/ (browser, focused_text, selection, navigation)                              |
| - image/ (focus_capture, objects, screen_curtain)                                                 |
| [ALLOWED: NVDA API, wx, gui, winUser, controlTypes, textInfos]                                     |
+-------------------------------------------------+-------------------------------------------------+
                                                  | imports
                                                  v
+---------------------------------------------------------------------------------------------------+
| LAYER 1: APPLICATION ORCHESTRATION & PRESENTATION                                                  |
| - plugin/application.py (AIAssistantApplication facade)                                            |
| - plugin/presenter.py (Presentation intent, ActionStore, speech marshaling)                       |
| - ui/adapter.py (UIAdapter, host process supervisor, fallback policy)                             |
| - service/worker_client.py (JobClient, SessionManager IPC proxy)                                  |
| [ALLOWED: standard library, Layer 2 domain types; NO direct NVDA imports]                         |
+-------------------------------------------------+-------------------------------------------------+
                                                  | imports
                                                  v
+---------------------------------------------------------------------------------------------------+
| LAYER 2: PURE-PYTHON DOMAIN & SERVICES (Zero NVDA Dependencies)                                    |
| - core/ (canonical messages, tool schemas, event DTOs, job/session FSM)                            |
| - config/ (state models, YAML store, model config, language resolver port)                        |
| - use_case/ (engine, registry, summary, proofread, chat workspace)                                |
| - prompts/ (Jinja2 templates, assembly, token budgeting)                                          |
| - tools/ (registry, execution, schemas)                                                           |
| - context/ (types, reduction, formatting, graph_store, budget)                                    |
| - service/ (LLM service, chat coordinator, ModelManagementService, error reporter)                |
| - providers/ (registry, capabilities, adapters: openai_compat, anthropic, etc.)                   |
| [STRICTLY FORBIDDEN: ALL NVDA MODULES (Enforced by Ruff TID251 & AST test gate)]                  |
+-------------------------------------------------+-------------------------------------------------+
                                                  | IPC Named Pipes (Versioned DTOs)
                                                  v
+---------------------------------------------------------------------------------------------------+
| LAYER 3: OUT-OF-PROCESS WORKER ENGINE (ai_assistant_worker.exe)                                    |
| - worker/server.py (Named pipe server, handshake validator, frame decoder)                        |
| - worker/dispatch.py (Priority Job Queue, ThreadPoolExecutor, cancellation tokens)                |
| - worker/executors/ (DownloadExecutor, ChecksumVerifier, UnpackExecutor)                          |
| - worker/sessions/ (OcrSessionManager [N=2 queue], AudioTranscriptionSession [10s ring buffer])   |
| - providers/runtime/ (RuntimeSupervisor PyO3 bindings, OsProcessDriver, HealthChecker)            |
| - embeddings/ (Candle EmbeddingEngine PyO3 bindings)                                              |
+-------------------------------------------------+-------------------------------------------------+
                                                  | Child Processes (Job Object Managed)
                                                  v
+---------------------------------------------------------------------------------------------------+
| LAYER 4: NATIVE RUNTIMES (litert-lm, llama-server.exe, nvda_ui_host.exe)                          |
+---------------------------------------------------------------------------------------------------+
```

---

## 5. Complete Thread & Executor Map

### 5.1 Concurrency Master Classification Table (Audit B)

All 55 production concurrency constructs across the repository at `ced1cbc` are cataloged and classified:

| Construct ID | Exact File Path & Lines (`ced1cbc`) | Construct Name / Type | Current Role | Target Classification | Target Disposition / Rationale |
|---|---|---|---|---|---|
| **CC-01** | `plugin/background.py:371` | `self._closed` (`threading.Event`) | Background runner cancellation | **MOVE TO WORKER** | Replaced by Worker job cancellation protocol (`CancellationToken`). |
| **CC-02** | `plugin/background.py:372–373` | `self._threads` & `_threads_lock` | Worker thread tracking set | **REMOVE/CONSOLIDATE** | Eliminated when background execution moves to Worker process. |
| **CC-03** | `plugin/background.py:396` | `AIassistant{title}Worker` (`Thread`) | Use case execution thread | **MOVE TO WORKER** | Use cases submitted as typed jobs to Worker process. |
| **CC-04** | `plugin/background.py:404` | `BrowserAssistantModelPreload` (`Thread`)| Model preload worker | **MOVE TO WORKER** | Model preload submitted as background Worker job. |
| **CC-05** | `plugin/background.py:80` | `litert-restart-on-config-change` (`Thread`)| Local server restart | **REMOVE/CONSOLIDATE** | Managed locally by Worker; NVDA sends config update over IPC. |
| **CC-06** | `plugin/background.py:105` | `llama-shutdown-on-config-change` (`Thread`)| Local server shutdown | **REMOVE/CONSOLIDATE** | Managed locally by Worker; NVDA sends config update over IPC. |
| **CC-07** | `plugin/application.py:178` | `LiteRTServerShutdown` (`Thread`) | Server shutdown on exit | **REMOVE/CONSOLIDATE** | Worker process manages runtime supervisor child teardown. |
| **CC-08** | `plugin/application.py:186` | `LlamaServerShutdown` (`Thread`) | Server shutdown on exit | **REMOVE/CONSOLIDATE** | Worker process manages runtime supervisor child teardown. |
| **CC-09** | `plugin/application.py:202` | `ProviderStateChange` (`Thread`) | State change IPC deferral | **REMOVE/CONSOLIDATE** | Session state sync handled asynchronously via Worker IPC. |
| **CC-10** | `plugin/application.py:354` | `AccessibilityGraphCapture` (`Thread`) | Graph file saving thread | **MOVE TO WORKER** | Main thread snapshots graph; serialization handed to Worker. |
| **CC-11** | `plugin/application.py:414` | `{provider}ServerSwitchStart` (`Thread`)| Auto-start on provider switch | **MOVE TO WORKER** | Provider switch notifies Worker; Worker manages readiness. |
| **CC-12** | `plugin/application.py:478` | `ModelListFetch` (`Thread`) | Model catalog fetch thread | **MOVE TO WORKER** | NVDA reads pushed catalog snapshot; Worker handles fetching. |
| **CC-13** | `plugin/local_provider_startup.py:43`| `{provider}ServerAutoStart` (`Thread`) | Startup auto-start thread | **REMOVE/CONSOLIDATE** | Worker process auto-starts runtime supervisor on launch. |
| **CC-14** | `ui/task_runner.py:28` | `UiDispatcher.post` (`wx.CallAfter`) | wx event loop dispatch | **KEEP IN NVDA** | Required for NVDA wxWidgets settings and fallback dialogs. |
| **CC-15** | `ui/task_runner.py:40–41` | `TaskHandle` (`Event`, `Future`) | Task cancellation handle | **REMOVE/CONSOLIDATE** | Replaced by Worker job handles. |
| **CC-16** | `ui/task_runner.py:62` | `ThreadPoolExecutor(4)` | UI background task pool | **REMOVE/CONSOLIDATE** | Eliminated from NVDA; heavy dialog tasks run in Worker. |
| **CC-17** | `ui/adapter.py:38` | `self._command_queue` (`queue.Queue`) | Pipe command queue | **KEEP IN NVDA** | Serializes commands to `nvda_ui_host.exe` off NVDA main thread. |
| **CC-18** | `ui/adapter.py:42` | `self._worker_thread` (`Thread`) | Pipe command worker | **KEEP IN NVDA** | Processes `_command_queue` to `nvda_ui_host.exe`. |
| **CC-19** | `ui/adapter.py:222` | `handle_chat_submission` (`Thread`) | Chat submission thread | **MOVE TO WORKER** | Chat turn submitted as job to Worker process. |
| **CC-20** | `ui/host_transport.py:28` | `_stop_event` (`threading.Event`) | Transport stop signal | **KEEP IN NVDA** | Shuts down named pipe event listener. |
| **CC-21** | `ui/host_transport.py:30` | `_event_listener_lock` (`Lock`) | Event listener start lock | **KEEP IN NVDA** | Protects event listener thread initialization. |
| **CC-22** | `ui/host_transport.py:41` | `ui_host_event_listener` (`Thread`) | Pipe event reader thread | **KEEP IN NVDA** | Reads asynchronous events from `nvda_ui_host.exe`. |
| **CC-23** | `ui/host_process.py:16` | `_process_lock` (`threading.Lock`) | Host process state lock | **KEEP IN NVDA** | Synchronizes `nvda_ui_host.exe` start/stop calls. |
| **CC-24** | `ui/host_process.py:101` | `ui_host_stdout_reader` (`Thread`) | Host stdout reader thread | **KEEP IN NVDA** | Drains stdout of `nvda_ui_host.exe` for logging. |
| **CC-25** | `ui/host_lifecycle.py:19` | `_lock` (`threading.RLock`) | Host lifecycle lock | **KEEP IN NVDA** | Tracks UI host state (`STOPPED`, `READY`, `FAILED`). |
| **CC-26** | `ui/action_store.py:12` | `_lock` (`threading.RLock`) | Action store payload lock | **KEEP IN NVDA** | Protects UI action tokens consumed by NVDA gestures. |
| **CC-27** | `ui/nvda_ui.py:17` | `_streaming_tone_lock` (`Lock`) | Streaming tone throttle | **KEEP IN NVDA** | Throttles progress beep frequency on NVDA event thread. |
| **CC-28** | `ui/nvda_ui.py:163` | `call()` (`done.wait()`, `Event`) | Main-thread executor event | **KEEP IN NVDA** | Synchronous main-thread snapshot bridge; must add 5s timeout. |
| **CC-29** | `ui/nvda_ui.py:156` | `queue()` (`queueFunction`) | NVDA event queue marshal | **KEEP IN NVDA** | Canonical non-blocking marshaler to NVDA event loop. |
| **CC-30** | `ui/host_renderer.py:170` | `_dispatch_event_to_nvda` | Event queue marshal | **KEEP IN NVDA** | Marshals host pipe events onto NVDA event queue. |
| **CC-31** | `ui/download_progress.py:83–84`| `_cancel_event` & `_completion_lock`| Download dialog synchronization| **KEEP IN NVDA** | Synchronizes wx progress dialog cancellation and completion. |
| **CC-32** | `ui/download_progress.py:247` | Download worker (`Thread`) | Dialog download thread | **MOVE TO WORKER** | Downloads move to Worker; dialog listens to progress IPC. |
| **CC-33** | `service/model_cache.py:65` | `_FetchGate.event` (`Event`) | Fetch deduplication barrier | **MOVE TO WORKER** | Deduplication barrier moves to Worker model manager. |
| **CC-34** | `service/model_cache.py:85` | `ModelCatalogCache._lock` (`RLock`) | Catalog cache lock | **MOVE TO WORKER** | Cache management moves to Worker; NVDA gets snapshot. |
| **CC-35** | `service/model_cache.py:190` | `ModelCatalogPreload` (`Thread`) | Background catalog preload | **MOVE TO WORKER** | Catalog discovery executed entirely in Worker. |
| **CC-36** | `service/model_cache.py:212` | `ModelCatalogFetch-{provider}` (`Thread`)| Background fetch thread | **MOVE TO WORKER** | Network fetching executed entirely in Worker. |
| **CC-37** | `service/model_cache.py:397` | `ModelCapabilityCache._lock` (`RLock`)| Capability cache lock | **MOVE TO PURE PYTHON** | Pure in-memory capability lookup. |
| **CC-38** | `service/chat/coordinator.py:53`| `_session_lock` (`threading.RLock`)| Session turn lock | **MOVE TO PURE PYTHON** | Domain-level turn synchronization in pure Python. |
| **CC-39** | `service/chat/coordinator.py:56`| `_turn_lock` (`threading.Lock`) | Turn atomic lock | **MOVE TO PURE PYTHON** | Domain-level atomic turn synchronization. |
| **CC-40** | `service/base.py:48, 66` | `_lock` & `_active_worker` | Base coordinator worker | **REMOVE/CONSOLIDATE** | Dead code in `ChatCoordinator`; delete. |
| **CC-41** | `service/error_reporter.py:39` | `_lock` (`threading.Lock`) | Error reporter dedupe lock | **MOVE TO PURE PYTHON** | Pure domain error reporting history. |
| **CC-42** | `config/model_config.py:168` | `_lock` (`threading.RLock`) | Model config store lock | **MOVE TO PURE PYTHON** | Pure domain config persistence lock. |
| **CC-43** | `config/enabled_models.py:49` | `_lock` (`threading.RLock`) | Enabled models store lock | **MOVE TO PURE PYTHON** | Pure domain config persistence lock. |
| **CC-44** | `providers/_provider_runtime.py:26`| `_lock` (`threading.RLock`) | Active provider factory lock| **MOVE TO PURE PYTHON** | Pure domain provider swap lock. |
| **CC-45** | `providers/runtime/server.py:51`| `_CONFIG_WRITE_LOCK` (`Lock`) | LiteRT config file lock | **RUST-OWNED** | Runtime supervisor in Rust manages config generation. |
| **CC-46** | `providers/runtime/server.py:335`| `_TestShimSupervisor._lock` (`RLock`)| Duplicate test shim lock | **REMOVE/CONSOLIDATE** | Production test shim deleted (RS-10). |
| **CC-47** | `providers/runtime/llama_server.py:105`| `_LlamaServerProcess._lock` (`RLock`)| Duplicate test shim lock | **REMOVE/CONSOLIDATE** | Production test shim deleted (RS-10). |
| **CC-48** | `providers/runtime/llama_server.py:279`| `_models_cache_lock` (`Lock`) | llama model cache lock | **MOVE TO WORKER** | Worker owns llama catalog discovery. |
| **CC-49** | `providers/runtime/llama_server.py:530`| `_supervisors_lock` (`RLock`)| llama supervisor registry lock| **RUST-OWNED** | Rust `runtime_supervisor` manages process handles. |
| **CC-50** | `providers/runtime/download.py:85`| `cancel_event` (`Event`) | Runtime download cancel | **MOVE TO WORKER** | Worker process owns downloads and cancellation. |
| **CC-51** | `providers/runtime/model_download.py:71`| `cancel_event` (`Event`) | Model download cancel | **MOVE TO WORKER** | Worker process owns downloads and cancellation. |
| **CC-52** | `providers/capabilities.py:13` | `_registry_lock` (`RLock`) | Capabilities registry lock | **MOVE TO PURE PYTHON** | In-memory capability registry lock. |
| **CC-53** | `providers/runtime/llama_models.py:242`| `_lock` (`RLock`) | Preset catalog lock | **MOVE TO PURE PYTHON** | In-memory preset catalog lock. |
| **CC-54** | `runtime_supervisor/src/supervisor.rs:18`| `Mutex<SupervisorState>` | Rust supervisor state | **RUST-OWNED** | Authoritative process & lifecycle lock in Rust. |
| **CC-55** | `runtime_supervisor/src/supervisor.rs:19`| `Condvar` | Rust condvar notification | **RUST-OWNED** | Fencing & startup synchronization in Rust. |

### 5.2 Summary of Target Concurrency Disposition
- **KEEP IN NVDA**: 13 constructs (Strictly UI event queues, named pipe IO listeners, and modal dialog cancel handlers).
- **MOVE TO PURE PYTHON**: 9 constructs (In-memory locks for config, capability caches, chat coordinator turns).
- **MOVE TO WORKER**: 18 constructs (All background task execution, downloads, model preloading, catalog discovery, chat workers).
- **RUST-OWNED**: 5 constructs (Native Rust supervisor state mutex, condvars, and handle collections).
- **REMOVE/CONSOLIDATE**: 10 constructs (Redundant test shims, ad-hoc thread spawners, dead base classes).

### 5.3 Detailed Call-Chain Latency Spikes on NVDA Main Thread

#### Spike 1: Synchronous `time.sleep()` Retry Loop in Focus Capture [CONFIRMED, BLOCKER TA-01]
- **File & Lines**: `addon/globalPlugins/AI-assistant/image/focus_capture.py:107–124` in `_resolve_capture_location_with_retry()`.
- **Call Chain**:
  `Gesture` -> `BackgroundTaskRunner worker` (`background.py:444`) -> `context_pipeline.collect()` -> `_resolve_image_snapshots()` -> `nvda_ui.call(_capture_all)` -> **NVDA Main Event Thread** -> `_capture_region_and_metadata()` -> `_resolve_capture_location_with_retry()` -> `for attempt in range(max_attempts): time.sleep(0.1)`.
- **Observed Impact**: If focus location resolution is transiently unavailable (common in IA2 web controls and WebView2), the NVDA main loop is blocked for up to **400 ms**. Audio stutter, delayed key echo, and Windows marking NVDA "Not Responding" occur directly.
- **Resolution**: Eliminate all `time.sleep()` calls on the main thread. Fallback immediately through `focus.location` -> `navigator` -> `foreground` -> `winUser.getWindowRect(hwnd)` in < 1 ms.

#### Spike 2: Synchronous PIL PNG Compression on NVDA Main Thread [CONFIRMED, BLOCKER TA-03]
- **File & Lines**: `image/services.py:48–51` and `image/focus_capture.py:259–265`.
- **Observed Code**: `image = ImageGrab.grab(bbox=bbox); image.save(buffer, format="PNG")`.
- **Observed Impact**: PNG compression of high-DPI screens (e.g. 2560x1440 or 3840x2160) takes **50–250 ms** of pure CPU compression running synchronously on the NVDA main event loop.
- **Resolution**: Main thread captures raw GDI DIB bitmap bytes and passes them uncompressed to the Worker process. All LANCZOS resizing, PNG compression, and base64 encoding execute out-of-process. Main thread time drops from ~150 ms to < 5 ms.

#### Spike 3: Synchronous Full-DOM Text & Field Parsing [CONFIRMED, DESIGN DETAIL TA-08]
- **File & Lines**: `context/extractors/browser_field_parser.py:32–49` and `browser.py:70–85`.
- **Observed Impact**: Iterating virtual buffer field streams and computing SHA-256 hashes on large documents (10,000+ controls) takes **100–300 ms** on the main thread.
- **Resolution**: Snapshot raw text and control indices on the main thread; delegate graph construction, token counting, and hash calculation to Worker.

#### Spike 4: Unbounded `done.wait()` in `nvda_ui.call()` [CONFIRMED, BLOCKER TA-04]
- **File & Lines**: `ui/nvda_ui.py:163, 175`.
- **Observed Code**: `queueHandler.queueFunction(queueHandler.eventQueue, runner); done.wait()`.
- **Observed Impact**: If NVDA's event queue stops processing (modal dialog loops, shutdown queue purge), `done.wait()` hangs calling worker threads indefinitely.
- **Resolution**: Add explicit timeout: `if not done.wait(timeout=5.0): raise TimeoutError("NVDA main thread call timed out")`.

#### Spike 5: Synchronous Network Sockets on Cache Miss [CONFIRMED, BLOCKER TA-05]
- **File & Lines**: `service/model_cache.py:109–121, 410–413` and `service/provider_readiness.py:217–224, 337–344`.
- **Observed Impact**: Cold cache calls execute blocking HTTP requests directly on the calling thread. If called from gestures or UI initialization, NVDA freezes for up to the socket timeout (10–30s).
- **Resolution**: Non-blocking read-only cache snapshots on the NVDA side. Network fetching is executed exclusively in the Worker process.

#### Spike 6: Live NVDA COM Object Leakage via `navigation_context` [CONFIRMED, BLOCKER TA-02]
- **File & Lines**: `context/types.py:78`, `presenter.py:422`, `navigation.py:638`.
- **Hazard**: `BrowserExtractionSnapshot.navigation_context` holds a live `TreeInterceptor` or `NVDAObject` COM pointer. It is transmitted across thread boundaries into background workers and stored in `ResultActionStore`. If the browser tab is closed or reloaded, invoking methods on the dead COM pointer causes `RPC_E_DISCONNECTED` (`0x80010108`) or crash in `IAccessible2.dll`.
- **Resolution**: Replace `navigation_context` with immutable `TargetNavigationSpec` DTO containing pure primitives (`target_id`, `label`, `order_index`, `window_handle`). When navigation is triggered, NVDA re-resolves the tree interceptor cleanly on the main thread.

---

## 6. NVDA Import Map & Boundary Enforcement

### 6.1 Exhaustive Inventory of NVDA Imports (Audit C)

A complete AST audit across all 114 production Python files in `addon/globalPlugins/AI-assistant/` identified exactly **95 NVDA import statements**:

| NVDA Module | Statements | Current Locations | Remediation Strategy |
| :--- | :---: | :--- | :--- |
| `logHandler` | **40** | 18 domain/service files, 22 adapter files | Standardize pure code to `import logging; log = logging.getLogger(__name__)`. Attach NVDA log bridge only in NVDA shell. |
| `wx` | **10** | `ui/` dialogs, `plugin/controller.py` menu | Keep strictly confined to `ui/` native fallback dialogs and controller menu. |
| `gui` / `guiHelper` | **10** | `ui/` dialogs, `plugin/controller.py` | Keep strictly confined to `ui/` native fallback dialogs. |
| `api` | **8** | `context/extractors/`, `image/`, `utils/clipboard.py` | Confine to Layer 0 extractors. Relocate clipboard reading to `ui/nvda_ui.py`. |
| `textInfos` | **6** | `context/extractors/`, `context/navigation.py` | Confine strictly to Layer 0 extractors. |
| `treeInterceptorHandler` | **3** | `context/extractors/browser*.py` | Confine strictly to Layer 0 browser extractors. |
| `addonHandler` | **3** | `plugin/__init__.py`, `application.py`, `settings_panel.py` | Confine strictly to add-on metadata initialization. |
| `speech` | **3** | `ui/nvda_ui.py` | Confine strictly to `ui/nvda_ui.py`. |
| `controlTypes` | **2** | `context/extractors/browser_*.py` | Confine strictly to Layer 0 browser extractors. |
| `winUser` | **2** | `context/navigation.py`, `image/focus_capture.py` | Confine strictly to Layer 0 Win32 accessibility helpers. |
| `locationHelper` | **2** | `image/objects.py` | Confine strictly to Layer 0 image helpers. |
| `queueHandler` | **2** | `ui/nvda_ui.py`, `ui/host_renderer.py` | Confine strictly to `ui/nvda_ui.py`. |
| `tones` | **1** | `ui/nvda_ui.py` | Confine strictly to `ui/nvda_ui.py`. |
| `languageHandler` | **1** | `config/settings.py:8` | Decouple via pluggable `register_language_resolver` port. |
| `globalPluginHandler` | **1** | `plugin/controller.py:9` | Confine strictly to add-on entry point. |
| `scriptHandler` | **1** | `plugin/controller.py:13` | Confine strictly to gesture `@script` annotations. |
| **Total** | **95** | | |

### 6.2 Maximum Coherent Pure-Python Subtree (Invariants A5–A6)

Purging `logHandler` and decoupling `languageHandler` isolates **92 of the 114 Python files (80.7%)** into pure Python:
- `core/` (100% pure)
- `tools/` (100% pure)
- `use_case/` (100% pure)
- `embeddings/` (100% pure)
- `prompts/` (100% pure after removing 1 `logHandler` import)
- `service/` (100% pure after removing 5 `logHandler` imports)
- `providers/` (100% pure after removing 8 `logHandler` imports)
- `config/` (100% pure after removing 2 `logHandler` imports and decoupling `languageHandler`)
- `observability/` (100% pure after removing 1 `logHandler` import)
- `context/` reduction, formatting, types, graph_store (100% pure)

### 6.3 Automated Import Boundary Enforcement Rules

To permanently prevent regression and enforce Invariants A5–A6, two automated gates are established:

#### 1. Ruff Banned API Configuration (`pyproject.toml`)
```toml
[tool.ruff.lint]
extend-select = ["TID251"]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"logHandler".msg = "Use standard library 'logging.getLogger(__name__)' instead of NVDA logHandler."
"languageHandler".msg = "Access language via injected LanguageResolver port."
"api".msg = "NVDA api access is forbidden outside Layer 0 extractors."
"textInfos".msg = "textInfos is forbidden outside Layer 0 extractors."
"controlTypes".msg = "controlTypes is forbidden outside Layer 0 extractors."
"queueHandler".msg = "queueHandler is forbidden outside ui/nvda_ui.py."
"gui".msg = "gui is forbidden outside ui/ dialogs."
"wx".msg = "wx is forbidden outside ui/ dialogs."
"speech".msg = "speech is forbidden outside ui/nvda_ui.py."
"tones".msg = "tones is forbidden outside ui/nvda_ui.py."

[tool.ruff.lint.per-file-ignores]
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

#### 2. Automated Pure-Python AST Test Gate (`tests/tier1_pure/test_import_boundaries.py`)
Scans all AST nodes in pure directories in < 150 ms and asserts zero forbidden NVDA root module imports.

---

## 7. Test-Tier Redesign

### 7.1 Existing Test Suite Deficiencies (Audit D)
1. **Unconditional Sibling NVDA Checkout Lock**: Root `conftest.py:27–31` aborts test collection with `pytest.UsageError` if `../nvda/source/api.py` is absent, preventing even pure unit tests from running independently.
2. **Synthetic Package Namespace Boilerplate**: `tests/support/bootstrap.py` creates dynamic package names (`model_config_testpkg`) duplicated across all 59 test files to work around the directory hyphen (`AI-assistant`).
3. **Brittle Live COM Wrappers**: `uv run pytest -m nvda_integration` fails due to `oleacc.dll` timestamp drift in NVDA's generated comtypes wrapper (`comtypes._tlib_version_checker.py:18`).

### 7.2 The Three-Tier Test Architecture (Invariant A30)

```
┌────────────────────────────────┐ ┌────────────────────────────────┐ ┌────────────────────────────────┐
│   Tier 1: Pure Python Domain    │ │    Tier 2: Rust / Worker IPC   │ │   Tier 3: NVDA Integration    │
├────────────────────────────────┤ ├────────────────────────────────┤ ├────────────────────────────────┤
│ • Zero NVDA checkout needed    │ │ • Rust supervisor tests        │ │ • Pinned ../nvda checkout      │
│ • Runs on Linux, macOS, Win    │ │ • Worker named-pipe contracts  │ │ • Real NVDA API definitions    │
│ • Target execution: < 3s       │ │ • Job & session state machines │ │ • TreeInterceptors & wx GUI    │
│ • Automated AST import guards  │ │ • Target execution: < 8s       │ │ • Target execution: ~15s       │
│ • Command: uv run pytest tier1 │ │ • Command: uv run pytest tier2 │ │ • Command: uv run pytest tier3 │
└────────────────────────────────┘ └────────────────────────────────┘ └────────────────────────────────┘
```

- **Tier 1 (Pure Python Unit & Domain)**: Covers `core/`, `config/`, `prompts/`, `tools/`, `service/`, `providers/`, `use_case/`, `embeddings/`, protocol serialization, AST boundary checks. Requires ZERO NVDA source code. Target runtime: < 3.0s.
- **Tier 2 (Rust / Worker IPC)**: Covers native `runtime_supervisor` tests, named pipe transports, framing, handshake, heartbeat, job state machine, bounded queues, and circuit breaker tests. Target runtime: < 8.0s.
- **Tier 3 (NVDA Integration)**: Covers real NVDA object tree extractors (`browser_field_parser`, `focused_text`), `queueHandler`, wxPython dialogs, and controller gestures against pinned sibling checkout (`nvda-source.toml`). Target runtime: ~15.0s.

---

## 8. Rust Supervisor Audit & Findings

### 8.1 Findings Summary (Audit E)
The native Rust `runtime_supervisor` crate provides robust process isolation and releases the Python GIL correctly during blocking operations (`py.allow_threads`). However, four critical BLOCKER concurrency bugs must be fixed before expanding ownership:

| Finding ID | Classification | Location in `runtime_supervisor/src/` | Root Cause & Mechanism | Architectural Impact |
|---|---|---|---|---|
| **RS-01** | **CONFIRMED, BLOCKER** | `supervisor.rs:130–141, 358–370, 421–428` | Generation counter is NOT incremented when child exits with error or readiness times out. | External observers cannot detect state epoch boundary on crash; stale status updates overwrite newer states. Violates Invariant A9. |
| **RS-02** | **CONFIRMED, BLOCKER** | `supervisor.rs:168–275, 485–487` | Missing `Stopping` guard in `ensure_ready`. While `stop()` is awaiting old process exit, concurrent `ensure_ready` spawns new process; `stop()` then unconditionally overwrites state back to `Stopped`. | Spawned child process is orphaned as an untracked zombie holding GPU memory. Violates Invariants A7, A9. |
| **RS-03** | **CONFIRMED, BLOCKER** | `supervisor.rs:448–467` | `restart()` invokes `proc.terminate()` but never calls `wait()` or `wait_timeout()` before calling `ensure_ready()`. | Races socket release: old server re-adopted if dying socket responds, or new spawn crashes with `WSAEADDRINUSE`. Violates Invariant A9. |
| **RS-04** | **CONFIRMED, BLOCKER** | `supervisor.rs:223–269, 314–325` | Concurrent conflicting `ensure_ready` calls with different configs supersede each other in an unbounded loop. | Threads enter ping-pong livelock, endlessly killing each other's processes and incrementing generations. |
| **RS-05** | **CONFIRMED, LIKELY** | `health.rs:32–63, supervisor.rs:199–221` | `check_compatible` does not verify expected model name; `ReadyAdopted` state never rechecks config. | Unrelated server on port 9379/8080 adopted blindly; subsequent model configuration changes silently ignored. |
| **RS-06** | **CONFIRMED, DESIGN DETAIL** | `process.rs:27–56` | Child processes not assigned to Windows Job Object with `KILL_ON_JOB_CLOSE`. | Parent crash leaks child process tree and GPU memory allocations. |
| **RS-07** | **CONFIRMED, DESIGN DETAIL** | `process.rs:76–80, supervisor.rs:480–484`| Immediate forceful `TerminateProcess` bypasses graceful teardown. | Risks data corruption for memory-mapped GGUF files (`MapViewOfFile`). |
| **RS-08** | **CONFIRMED, DESIGN DETAIL** | `process.rs:44–45` | `stdout` and `stderr` redirected to `Stdio::null()`. | Missing DLLs, CUDA errors, and startup failures completely invisible. |
| **RS-09** | **CONFIRMED, DESIGN DETAIL** | `lib.rs:90, 119` | All errors mapped to generic `PyRuntimeError`. | Python callers forced to perform fragile string scraping. |
| **RS-10** | **CONFIRMED, BLOCKER** | `server.py:322–415, llama_server.py:191–258` | Duplicate Python test shims exist in production modules. | Violates Invariant A7 (single authoritative native owner). |
| **RS-11** | **CONFIRMED, DESIGN DETAIL** | `Cargo.toml:11` | Python 3.14 on system PATH fails build without ABI3 flag. | Requires `uv run cargo test` or `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`. |
| **RS-12** | **CONFIRMED, DESIGN DETAIL** | `lib.rs:80–89, 109–118` | GIL release verified correct across all blocking calls. | Main thread protected; long operations do not lock Python interpreter. |
| **RS-13** | **CONFIRMED, BLOCKER** | `plugin/background.py:51–112`, `server.py:544` | Supervisor runs in NVDA process rather than Worker boundary. | Violates Invariants A1, A25, and target process topology. |

### 8.2 Mandatory Rust Supervisor Fixes (Slice 0 & Pre-Implementation)
1. **Fix RS-01**: Increment `state.generation += 1` in all exit branches (`refresh_process_state_locked`, child crash exit, readiness timeout).
2. **Fix RS-02**: Add guard in `ensure_ready`: if `state.state == LifecycleState::Stopping`, wait on `condvar` until `Stopped`. In `stop()`, guard state write with `if state.generation == my_gen`.
3. **Fix RS-03**: In `restart()`, call `proc.wait_timeout(timeout)` before calling `ensure_ready()`, and verify port release.
4. **Fix RS-04**: When `ensure_ready` detects `Starting` with different config, wait on `condvar` for startup completion rather than preempting immediately.
5. **Fix RS-06 & RS-08**: Assign child handles to Windows Job Object and capture last 64 KB of `stderr` into an in-memory ring buffer.

---

## 9. LiteRT Flow Architecture

### 9.1 Current vs Target Execution Flow

```
[Current HEAD Flow]
Gesture -> NVDA Main Thread -> BackgroundTaskRunner (daemon thread)
  -> providers/runtime/server.py -> subprocess.run(litert-lm import) [BLOCKS 120s]
  -> RuntimeSupervisor (in-process Rust in nvda.exe) -> spawns python.exe serve
  -> HTTP POST /v1/chat/completions -> SSE streaming -> nvda_ui.queue(speech)

[Target Worker Flow]
Gesture -> NVDA Main Thread -> Synchronous DOM/Image Snapshot (< 5ms)
  -> Worker IPC Client (JobSubmission over \\.\pipe\nvda_worker_cmd) -> RETURN TO MAIN THREAD
  -> Worker Dispatch Engine -> ModelManagementService -> LiteRT Supervisor (out-of-process)
  -> HTTP POST /v1/chat/completions -> SSE streaming -> Worker emits StreamChunk over evt pipe
  -> NVDA IPC Listener Thread -> queueHandler.queueFunction(on_chunk) -> speech / WebUI
```

- **Variant Selection**: Evaluates GPU/CPU hardware capabilities (`has_gpu()` via `ctypes`) and selects prioritized candidate (`litert_models.py:310–348`).
- **Isolation Benefit**: Heavy model import CLI (120s) and memory-mapped inference run wholly inside the Worker process, completely isolated from `nvda.exe`.

---

## 10. llama.cpp Flow Architecture

### 10.1 Current vs Target Execution Flow

```
[Current HEAD Flow]
Gesture -> NVDA Main Thread -> BackgroundTaskRunner
  -> ensure_provider_server_ready() [SILENTLY MUTATES CONFIG IF MODEL MISSING]
  -> LlamaCppModelManager -> LlamaModelCatalog.write_preset(models.ini)
  -> RuntimeSupervisor (in-process in nvda.exe) -> spawns llama-server.exe
  -> HTTP POST /v1/chat/completions -> SSE streaming -> nvda_ui.queue(speech)

[Target Worker Flow]
Gesture -> NVDA Main Thread -> Synchronous DOM/Image Snapshot (< 5ms)
  -> Worker IPC Client (JobSubmission) -> RETURN TO MAIN THREAD
  -> Worker Dispatch Engine -> ModelManagementService.verify_runtime_ready()
     [FAIL-CLOSED: If model missing, reports UNAVAILABLE; ZERO SILENT FALLBACKS]
  -> LlamaSupervisor (out-of-process) -> spawns llama-server.exe under Job Object
  -> HTTP POST /v1/chat/completions -> SSE streaming -> Worker emits StreamChunk
  -> NVDA IPC Listener Thread -> queueHandler.queueFunction -> speech / WebUI
```

- **Elimination of Silent Mutation**: Purges `set_model_name(record.model_id)` in `background.py:194`. If the configured model is absent, returns typed error `MODEL_UNAVAILABLE`.

---

## 11. Current Model Responsibility Map

### 11.1 Fragmented Model State & Disjoint Enums (Audit F)

At HEAD (`ced1cbc`), model state is fractured across six incompatible representations:
1. `CatalogState` (`service/model_cache.py:35–40`): `COLD`, `LOADING`, `READY`, `EMPTY`, `ERROR`.
2. `ModelState` (`providers/model_manager.py:27–43`): `READY`, `DOWNLOADED`, `NOT_DOWNLOADED`, `DOWNLOADING`, `FAILED`.
3. `ConfiguredModelState` (`service/provider_readiness.py:21–29`): `VALID`, `NOT_CONFIGURED`, `UNAVAILABLE`, `DISABLED`, `UNKNOWN`.
4. `ProviderModelInfo` (`providers/interfaces.py:80–93`): Chat model metadata DTO.
5. `EmbeddingModelInfo` (`embeddings/manager.py:11–19`): Isolated Candle embedding DTO.
6. `LlamaModelRecord` (`providers/runtime/llama_models.py:18–60`): GGUF disk record DTO.

### 11.2 Key Deficiencies Identified
- **Synchronous HTTP in Readiness Check**: `ProviderReadinessService.evaluate()` sends synchronous HTTP GET to `/health` and `/v1/models` (`readiness.py:219, 340–344`), blocking callers.
- **Cold Cache False Positive**: If LiteRT catalog cache is `COLD`, `evaluate()` bypasses verification and reports `READY` (`readiness.py:196–210`), causing runtime crashes on inference.
- **Scattered Negative Visibility Filtering**: `ModelVisibilityStore` is queried independently across 5 modules, with UI layers forcefully re-injecting hidden models (`settings_panel.py:182–184`).
- **Disjoint Storage Hierarchies**: `models/litert-lm/`, `models/llama-cpp/`, and `models/embeddings/` maintain separate directories without a unified catalog manifest.

---

## 12. Target Model-Management Decomposition

### 12.1 Central `ModelManagementService` Architecture (Invariants A11–A15)

```
+---------------------------------------------------------------------------------------------------+
| Central ModelManagementService (Pure-Python Application Service)                                  |
|                                                                                                   |
|  +-----------------------------+  +-------------------------------+  +-------------------------+  |
|  | Unified Model Registry      |  | Central Download State Machine|  | Standard Storage Layout |  |
|  | - Modalities: CHAT, VISION, |  | - Single-flight deduplication |  | - %APPDATA%/.../models/ |  |
|  |   OCR, TRANSCRIPTION,       |  | - HTTP Range resume           |  | - inventory.json        |  |
|  |   EMBEDDING, TTS            |  | - Streaming SHA-256           |  | - atomic directory move |  |
|  | - ModelDescriptor index     |  | - Worker job execution        |  | - user source protect   |  |
|  +-----------------------------+  +-------------------------------+  +-------------------------+  |
|                                                                                                   |
|  +-------------------------------------------------------------+  +----------------------------+  |
|  | Non-Blocking Readiness & Negative Visibility Engine         |  | Resource Arbitration Engine|  |
|  | - Zero main-thread sockets; event-driven readiness cache    |  | - VRAM/RAM allocation tiers|  |
|  | - Centralized negative visibility; zero silent fallbacks    |  | - 60s idle model reaper    |  |
|  +-------------------------------------------------------------+  +----------------------------+  |
+-------------------------------------------------+-------------------------------------------------+
                                                  | Coordinates
                                                  v
+---------------------------------------------------------------------------------------------------+
| ModalityEngineCollaborators:                                                                      |
| - ChatModelCollaborator          - VisionModelCollaborator         - OcrModelCollaborator         |
| - TranscriptionCollaborator      - EmbeddingModelCollaborator      - TtsModelCollaborator         |
+---------------------------------------------------------------------------------------------------+
```

### 12.2 Unified `ModelDescriptor` Specification (Invariant A11)

```python
class Modality(str, Enum):
    CHAT = "chat"
    VISION = "vision"
    OCR = "ocr"
    TRANSCRIPTION = "transcription"
    EMBEDDING = "embedding"
    TTS = "tts"

@dataclass(frozen=True, slots=True)
class ModelResourceSpec:
    ram_bytes: int
    vram_bytes: int
    compute_target: Literal["cpu", "gpu", "npu", "universal"] = "universal"
    context_window: int | None = None

@dataclass(frozen=True, slots=True)
class ModelSourceSpec:
    kind: Literal["cloud_endpoint", "huggingface_file", "huggingface_repo", "direct_url", "local_file"]
    location: str
    filename: str
    revision: str = "main"
    sha256: str | None = None
    auth_required: bool = False

@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    model_id: str
    display_name: str
    provider_id: str
    modality: Modality
    capabilities: frozenset[str]
    source: ModelSourceSpec
    resources: ModelResourceSpec
    priority: int = 100
    description: str = ""
    canonical_group_id: str | None = None
```

### 12.3 Multi-Modal Resource Arbitration Matrix (Invariant A15)

| Hardware Profile | System RAM | Detected VRAM | Concurrency Policy | Allocation / Coexistence Rules |
| :--- | :--- | :--- | :--- | :--- |
| **Low-End (Integrated / CPU)** | < 16 GB | < 2 GB | 1 Active Model | Strict exclusive locking: unload active model before loading another modality. |
| **Mid-Range (Budget GPU)** | 16–32 GB | 4–6 GB | 1 GPU LLM + 1 CPU Helper | LLM on GPU (capped ctx 4K–8K); OCR / Embedding pinned to CPU/XNNPACK. |
| **High-End (Discrete GPU)** | >= 32 GB | >= 8 GB | 1 GPU LLM + 1 GPU OCR / Whisper | Dynamic VRAM partitioning: 70% VRAM reserved for LLM, 30% for OCR / Whisper. |

- **Idle Reaper**: One-shot OCR or Vision models automatically unloaded after 60s idle timeout to reclaim VRAM.
- **Fail-Closed Policy**: If configured model is absent, system reports `MODEL_UNAVAILABLE` and never silently alters settings.

---

## 13. Current Background-Task Map

### 13.1 Deconstruction of `plugin/background.py` (Audit G)

`plugin/background.py` (495 lines) conflates 5 distinct responsibilities:

| Symbol in `background.py` | Lines | Current Responsibilities | Target Destination Module | Architectural Rationale |
| :--- | :---: | :--- | :--- | :--- |
| `_NON_LLM_USE_CASES` | 42–44 | Set of use cases skipping readiness gate | `use_case/routing.py` | Pure routing policy belongs with use cases. |
| `_on_litert_server_config_changed` | 51–85 | Config change listener; spawns restart worker | `providers/runtime/supervisor_service.py` | Local runtime config listeners belong in runtime service. |
| `_restart_litert_server_worker` | 87–98 | Worker body restarting LiteRT server | Worker Process Host | Supervisor commands execute in Worker process. |
| `_on_llama_server_config_changed` | 103–112 | Config change listener; stops stale servers | `providers/runtime/supervisor_service.py` | Local runtime config listeners belong in runtime service. |
| `ensure_litert_server_ready` | 115–138 | Gate for LiteRT readiness | `providers/litert_manager.py` | Provider-specific readiness gate in provider adapter. |
| `_ensure_litert_server_ready_core`| 140–162 | Verifies installation, ready state, model import | `providers/litert_manager.py` | Provider-specific orchestration. |
| `ensure_provider_server_ready` | 163–204 | Multi-provider server readiness coordinator & fallback | `service/provider_readiness.py` | Central application service coordinating readiness. |
| `_ensure_litert_server_ready_locked`| 205–210| Deprecated test shim alias | **REMOVE** | Obsolete test shim; delete during refactoring. |
| `_ensure_model_imported` | 212–308 | Checks catalog, resolves variants, imports model | `providers/litert_manager.py` | Model catalog and import mechanics in model management. |
| `_build_import_candidates` | 310–348 | Evaluates GPU/CPU variants for import | `providers/litert_models.py` | Pure hardware inspection and artifact selection. |
| `BackgroundTaskRunner` | 357–495 | Task executor, thread tracker, speech queue | Decomposed into: (1) `service/worker_client.py`, (2) `plugin/presenter.py` | Generic execution moves to Worker IPC; speech to presenter. |
| `start_model_preload` | 404–440 | Preloads active model and speaks status | `service/model_management/preload.py` | Orchestration in model management; speech in presenter. |
| `run_use_case_in_background` | 441–495 | Runs use case engine, handles errors, calls presenter | `use_case/engine.py` / `JobClient` | Use case execution in UseCaseEngine; marshaling in Presenter. |

---

## 14. Worker IPC Architecture (Versioning, Handshake, Protocol)

### 14.1 Versioned Handshake & Capability Negotiation (Invariant A17)

```
NVDA Client                                            Worker Server
     |                                                       |
     | ----- HandshakeRequest (v1.0.0, capabilities) ------> |
     |                                                       | (Validate version,
     |                                                       |  check compatibility)
     | <---- HandshakeResponse (accepted=True, ...) -------- |
     |                                                       |
   [Handshake Established: Channel Ready for Work Submission]
```

- **Protocol Version**: `"1.0.0"` (SemVer: major breaking, minor backward-compatible additions, patch bug fixes).
- **Capability Negotiation**: Features (`"job.model_download"`, `"job.inference"`, `"session.ocr"`, `"session.transcription"`, `"runtime.litert"`, `"runtime.llama"`) explicitly confirmed before dispatch.

### 14.2 Transport Architecture: Bi-Directional Named Pipes (Invariant A18)
- **Command Pipe** (`\\.\pipe\nvda_ai_assistant_worker_cmd`): Duplex RPC pipe for `JobSubmission`, `JobCancellationRequest`, `SessionControlCommand`, and `WorkerHealth`.
- **Event Pipe** (`\\.\pipe\nvda_ai_assistant_worker_evt`): Duplex asynchronous streaming pipe for `JobUpdate`, `JobResult`, `StreamChunk`, and `WorkerHealthEvent`.
- **Win32 Security DACL**: Pipe security descriptor restricts access strictly to current user SID (`TOKEN_USER`) and `Administrators`, rejecting unauthorized local accounts.

### 14.3 Framing & Transport Protocols
- **Control Plane Framing (NDJSON)**: Newline-delimited UTF-8 JSON (`\n` terminated). Max frame size: 16 MB.
- **Streaming Plane Hybrid Binary Framing**:
  ```
  +-----------------------+-----------------------+-----------------------+
  | Magic Header (4 bytes)| JSON Header Len (4B)  | Binary Payload Len(4B)|
  | 0xAA 0x55 0x01 0x00   | uint32 big-endian     | uint32 big-endian     |
  +-----------------------+-----------------------+-----------------------+
  | JSON Metadata Header (StreamChunk DTO without raw bytes)             |
  +-----------------------------------------------------------------------+
  | Raw Binary Bytes (BGRA/JPEG image pixels or 16-bit PCM audio)         |
  +-----------------------------------------------------------------------+
  ```
  Enables zero-copy slicing for video frames and audio PCM, eliminating 33% base64 encoding overhead.

### 14.4 Heartbeat, Liveness Probing & Generation Fencing (Invariant A19)
- **Heartbeat**: 5.0-second ping interval; 15.0-second timeout threshold (3 missed pings).
- **Pipe Disconnection**: Win32 `ERROR_BROKEN_PIPE` (`winerror=109`) detects worker crash in **< 5 ms**.
- **Monotonic Generation Fencing**: Integer `generation` counter increments on every spawn/restart. Incoming messages with `generation < active_generation` are discarded.

---

## 15. Job & Session State Model

### 15.1 Discrete Job Finite State Machine (Invariant A21)

```
      +---------------+
      |   SUBMITTED   | (Created by NVDA Client)
      +---------------+
              |
              v (Enqueued in Worker Queue)
      +---------------+
      |    QUEUED     |
      +---------------+
              |
              v (Worker thread claims job)
      +---------------+
      |    RUNNING    | <----+ (Emits periodic JobUpdate)
      +---------------+      |
        |     |     |  +-----+
        |     |     |
        |     |     +-------------------------+
        |     v [Success]                     | [Failure / Error]
        |   +---------------+                 v
        |   |   COMPLETED   | (Terminal)    +---------------+
        |   +---------------+               |    FAILED     | (Terminal)
        |                                   +---------------+
        v [Cancel Token Triggered]
      +---------------+
      |   CANCELLED   | (Terminal)
      +---------------+
```

- **Monotonic Invariant**: States advance strictly forward. Once reaching `COMPLETED`, `FAILED`, or `CANCELLED`, state is immutable.
- **Single Result Invariant**: Exactly one terminal `JobResult` is emitted per job.

### 15.2 Deterministic Two-Phase Cancellation Protocol (Invariant A22)
1. **Phase 1 (Cooperative Cancellation)**: NVDA sends `JobCancellationRequest`. Worker sets `CancellationToken`. The task checks token at fine-grained yield points (every 64 KB download, every extracted file, every generated token) and exits gracefully within 100 ms.
2. **Phase 2 (Preemption Escalation)**: If task does not exit within 3.0 seconds, the supervisor terminates the child process or recycles the worker process, guaranteeing NVDA never hangs.

### 15.3 Continuous Session Finite State Machine (Invariant A23)

```
      +---------------+
      |     INIT      | (SessionConfig proposed)
      +---------------+
              |
              v (Worker allocates model & ring buffer)
      +---------------+
      |  CONFIGURING  |
      +---------------+
              |
              v (Resources ready)
      +---------------+      Pause Command
      |     READY     | ----------------------+
      +---------------+                       |
              |                               v
   Stream Start | Stream Resumed       +---------------+
              v                        |    PAUSED     |
      +---------------+ -------------> +---------------+
      |   STREAMING   |  Pause Command
      +---------------+
              |
              v [Close Command / Stream End]
      +---------------+
      |    CLOSING    | (Flush buffers, emit final chunks)
      +---------------+
              |
              v (Deallocated)
      +---------------+               +---------------+
      |    CLOSED     | (Terminal)    |     ERROR     | (Terminal)
      +---------------+               +---------------+
```

### 15.4 Bounded Streaming for Continuous Modalities (Invariant A29)
1. **OCR Session Foundation (Slice 9)**:
   - **Bounded Queue ($N=2$)**: Slot 0 (Active Inference), Slot 1 (Pending Capture).
   - **Latest-Wins Frame Dropping**: If Slot 0 is busy when a new frame arrives, it overwrites Slot 1, immediately dropping the older unstarted frame. Inference in Slot 0 is never interrupted. Zero latency accumulation.
2. **Transcription Session Foundation (Slice 10)**:
   - **Circular Audio Ring Buffer**: Fixed 10.0-second unmanaged buffer (320 KB for 16 kHz 16-bit PCM).
   - **Silero/Energy VAD**: Discards non-speech frames before acoustic inference.
   - **Partial vs Finalized Transcript Hypotheses**:
     - *Partial* (`is_partial = True`, < 200 ms latency): Tentative speech in progress displayed/spoken transiently.
     - *Finalized* (`is_partial = False`, at phrase/pause boundary): Permanent text committed to conversation history.

---

## 16. Immutable DTO Definitions & Schemas

### 16.1 Authoritative Python Dataclasses (Invariant A24)

All DTOs are `@dataclass(frozen=True, slots=True)` with zero mutable fields:

```python
from __future__ import annotations
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

class JobStatus(StrEnum):
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class SessionState(StrEnum):
    INIT = "init"
    CONFIGURING = "configuring"
    READY = "ready"
    STREAMING = "streaming"
    PAUSED = "paused"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"

class ModalityType(StrEnum):
    DOWNLOAD = "download"
    INFERENCE = "inference"
    OCR = "ocr"
    TRANSCRIPTION = "transcription"
    EMBEDDING = "embedding"
    TTS = "tts"

@dataclass(frozen=True, slots=True)
class HandshakeRequest:
    protocol_version: str = "1.0.0"
    client_name: str = "nvda_ai_assistant"
    client_version: str = "1.0.0"
    client_pid: int = 0
    supported_schemas: tuple[str, ...] = ("job.v1", "session.v1", "health.v1")
    requested_capabilities: tuple[str, ...] = (
        "job.model_download", "job.model_verify", "job.inference",
        "session.ocr", "session.transcription",
    )
    request_id: str = field(default_factory=lambda: str(uuid4()))

@dataclass(frozen=True, slots=True)
class HandshakeResponse:
    accepted: bool
    protocol_version: str
    worker_pid: int
    worker_version: str
    negotiated_capabilities: tuple[str, ...]
    max_frame_bytes: int = 16 * 1024 * 1024
    error_message: str | None = None
    correlation_id: str = ""

@dataclass(frozen=True, slots=True)
class JobSubmission:
    job_id: str
    job_type: str
    payload: dict[str, Any]
    priority: int = 10
    timeout_seconds: float = 300.0
    generation: int = 1
    created_at_epoch_ms: int = 0

@dataclass(frozen=True, slots=True)
class JobUpdate:
    job_id: str
    status: JobStatus
    progress_pct: float = 0.0
    status_message: str = ""
    bytes_completed: int = 0
    bytes_total: int = 0
    throughput_bytes_per_sec: float = 0.0
    eta_seconds: float | None = None
    generation: int = 1
    timestamp_epoch_ms: int = 0

@dataclass(frozen=True, slots=True)
class JobResult:
    job_id: str
    status: JobStatus
    result_data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retriable: bool = False
    duration_ms: int = 0
    generation: int = 1

@dataclass(frozen=True, slots=True)
class SessionConfig:
    session_id: str
    modality: ModalityType
    config_parameters: dict[str, Any]
    max_queue_depth: int = 2
    buffer_capacity_ms: int = 10000
    generation: int = 1

@dataclass(frozen=True, slots=True)
class StreamChunk:
    session_id: str
    sequence_number: int
    is_partial: bool
    payload_text: str
    start_ms: int = 0
    end_ms: int = 0
    confidence: float = 1.0
    bounding_boxes: tuple[dict[str, Any], ...] = ()
    dropped_frames_count: int = 0
    generation: int = 1

@dataclass(frozen=True, slots=True)
class WorkerHealth:
    worker_pid: int
    generation: int
    uptime_seconds: float
    active_jobs_count: int
    active_sessions_count: int
    cpu_percent: float
    rss_memory_bytes: int
    gpu_available: bool = False
    gpu_memory_used_bytes: int = 0
    gpu_memory_total_bytes: int = 0
    is_healthy: bool = True
    error_summary: str | None = None
```

### 16.2 JSON Schemas (Draft 2020-12)
Complete JSON schemas are defined in `design_worker_ipc_1/design_report.md:758–900` for all 8 DTOs, validating properties, types, required fields, and preventing additional properties.

---

## 17. Migration Slices (Slices 0–10 Implementation Plans)

### Slice 0: Audit + Architecture Contract
- **Goal**: Establish the authoritative architecture baseline, fix blocking bugs in `runtime_supervisor/`, eliminate main-thread `time.sleep()`, add timeout to `nvda_ui.call()`, and freeze contracts.
- **Files Modified**:
  - `runtime_supervisor/src/supervisor.rs` (Fix RS-01, RS-02, RS-03, RS-04).
  - `addon/globalPlugins/AI-assistant/image/focus_capture.py` (Remove `time.sleep()` in `_resolve_capture_location_with_retry()`, TA-01).
  - `addon/globalPlugins/AI-assistant/ui/nvda_ui.py` (Add 5.0s timeout to `done.wait()` in `call()`, TA-04).
  - `addon/globalPlugins/AI-assistant/ui/adapter.py:410` (Wrap error in `nvda_ui.queue()`, TA-07).
- **Verification Gate**: `cargo test --manifest-path runtime_supervisor/Cargo.toml` (11+ passed), `uv run ruff check .`, `uv run pytest`.

### Slice 1: Pure Python Test Boundary
- **Goal**: Decouple domain/service code from NVDA checkout. Establish 3-tier test structure, abstract logging and language resolver, eliminate synthetic namespace boilerplate.
- **Files Modified/Created**:
  - `addon/globalPlugins/AI-assistant/utils/logger.py` (Standard library logging bridge).
  - Purge `from logHandler import log` from all 18 domain/service files (`config/state.py`, `service/model_cache.py`, etc.).
  - `addon/globalPlugins/AI-assistant/config/settings.py` (Decouple `languageHandler` via `register_language_resolver`).
  - `conftest.py` (Universal pure-Python root conftest; zero `../nvda` checkout requirement).
  - `tests/tier3_nvda/conftest.py` (Scoped NVDA checkout bootstrap).
  - `tests/tier1_pure/test_import_boundaries.py` (Automated AST boundary test).
  - `pyproject.toml` (Ruff `TID251` banned API rules).
- **Verification Gate**: `uv run pytest tests/tier1_pure/` passes in < 3s without `../nvda` checkout present.

### Slice 2: Job Domain / Protocol
- **Goal**: Implement pure Python Job and Session Finite State Machines and immutable DTOs without external process dependencies.
- **Files Created**:
  - `core/job/state.py` (`JobStateMachine`, `SessionStateMachine`).
  - `core/job/dto.py` (All 8 frozen DTOs with JSON serialization).
  - `core/job/cancellation.py` (`CancellationToken`, `CancellationCoordinator`).
  - `context/types.py` (Replace `BrowserExtractionSnapshot.navigation_context` with `TargetNavigationSpec` DTO, TA-02).
- **Verification Gate**: Pure-Python unit tests in `tests/tier1_pure/job/` verifying all state transitions, JSON round-tripping, and immutability invariants.

### Slice 3: Worker Process Lifecycle & IPC
- **Goal**: Build the Worker process launcher, Windows Job Object containment, named pipe transport, versioned handshake, and heartbeat watchdog.
- **Files Created/Modified**:
  - `worker/process.py` (Worker process entrypoint and runner).
  - `worker/ipc/transport.py` (Named pipe server with Win32 DACLs and NDJSON framing).
  - `worker/ipc/handshake.py` (Handshake validator).
  - `plugin/worker_supervisor.py` (NVDA-side `WorkerSupervisor`, process watchdog, generation fence, circuit breaker).
  - `service/worker_client.py` (`JobClient`, `SessionManager`).
- **Verification Gate**: Multi-process integration tests in `tests/tier2_worker/` verifying process spawning, pipe handshake, crash detection (< 5ms), and graceful restart.

### Slice 4: One Real Heavy Operation (Model Download)
- **Goal**: Migrate runtime and model downloading, SHA-256 hashing, and ZIP extraction from `download.py` into Worker job execution.
- **Files Created/Modified**:
  - `worker/executors/download.py` (HTTP Range streaming downloader).
  - `worker/executors/verify.py` (Streaming SHA-256 verifier).
  - `worker/executors/unpack.py` (Atomic directory unpacker).
  - `providers/runtime/download_client.py` (NVDA-side client submitting `JobSubmission(job_type="model_download")`).
  - `ui/download_progress.py` (Listens to `JobUpdate` events over IPC).
- **Verification Gate**: Download integration test verifying progress reporting, range resume on interruption, checksum verification, atomic unpacking, and cancellation cleanup.

### Slice 5: Model Management Application Boundary
- **Goal**: Centralize all model management into pure-Python `ModelManagementService`. Unify storage under `%APPDATA%/.../models/`. Centralize negative visibility filtering.
- **Files Created/Modified**:
  - `service/model_management/service.py` (`ModelManagementService`).
  - `service/model_management/descriptors.py` (`ModelDescriptor`, `ModelResourceSpec`, `ModelSourceSpec`).
  - `service/model_management/arbitration.py` (Resource arbitration engine, 60s idle reaper).
  - `config/enabled_models.py` (Owned exclusively by `ModelManagementService`).
  - Deprecate `service/model_cache.py` and `providers/model_manager.py`.
- **Verification Gate**: Unit tests verifying non-blocking readiness queries, zero silent fallbacks, and multi-modal resource arbitration under memory limits.

### Slice 6: LiteRT Runtime Ownership Moved to Worker
- **Goal**: Move `RuntimeSupervisor("litert-lm")` and CLI model import out of `nvda.exe` into the Worker process.
- **Files Modified**:
  - `worker/executors/litert.py` (Worker-side supervisor host).
  - `providers/litert_manager.py` (Routes server lifecycle commands over Worker IPC).
  - Remove in-process LiteRT supervisor instantiation from `server.py`.
- **Verification Gate**: LiteRT server starts and stops under Worker supervision; crash of `litert-lm` leaves `nvda.exe` 100% stable.

### Slice 7: llama.cpp Runtime Ownership Moved to Worker
- **Goal**: Move `RuntimeSupervisor("llama-server")` and router preset generation out of `nvda.exe` into the Worker process.
- **Files Modified**:
  - `worker/executors/llama.py` (Worker-side llama supervisor host).
  - `providers/llama_manager.py` (Routes lifecycle commands over Worker IPC).
  - Remove in-process llama supervisor from `llama_server.py`.
- **Verification Gate**: llama-server starts and stops under Worker supervision; model switching passes through Worker.

### Slice 8: Removal of Obsolete NVDA-Side Runtime Threading
- **Goal**: Deconstruct `plugin/background.py`. Delete obsolete Python test shims and unmanaged daemon threads.
- **Files Modified/Deleted**:
  - `plugin/background.py` (Delete `_on_litert_server_config_changed`, `_restart_litert_server_worker`, `_on_llama_server_config_changed`, `BackgroundTaskRunner`).
  - `plugin/application.py` (Delete `LiteRTServerShutdown`, `LlamaServerShutdown` daemon threads).
  - `providers/runtime/server.py` (Delete `_TestShimSupervisor`, RS-10).
  - `providers/runtime/llama_server.py` (Delete `_LlamaTestShimSupervisor`, RS-10).
- **Verification Gate**: Zero ad-hoc threads spawned during startup/shutdown; zero shadow test shims in production code.

### Slice 9: OCR Session Foundation
- **Goal**: Implement continuous OCR session support with bounded frame queue ($N=2$) and latest-wins frame dropping.
- **Files Created**:
  - `worker/sessions/ocr.py` (Bounded frame queue manager, drop counter).
  - `worker/executors/ocr_engine.py` (OCR executor interface).
  - `plugin/ocr_session_client.py` (Screen capture pipe client).
- **Verification Gate**: High-framerate producer test (30 FPS input vs 4 FPS OCR) confirms queue depth never exceeds 2, latest-wins dropping operates smoothly, and memory remains flat.

### Slice 10: Transcription Session Foundation
- **Goal**: Implement continuous audio transcription session with bounded 10-second circular ring buffer and partial vs finalized transcript semantics.
- **Files Created**:
  - `worker/sessions/transcription.py` (10s circular audio ring buffer, overflow guard).
  - `worker/executors/vad.py` (Voice activity filter).
  - `worker/executors/whisper_engine.py` (Hypothesis generator emitting `is_partial=True` and `is_partial=False`).
  - `plugin/transcription_client.py` (Audio microphone capture adapter).
- **Verification Gate**: Audio stream test verifying buffer size capped at 320 KB, partial hypotheses emitted < 200 ms, finalized emitted on pause/VAD silence, and zero capture stalls.

---

## 18. Acceptance Tests per Slice

| Slice | Test Command | Key Assertions / Acceptance Criteria |
| :--- | :--- | :--- |
| **Slice 0** | `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml`<br>`uv run pytest tests/ui/test_nvda_ui.py tests/image/test_focus_capture.py` | Generation counter increments on crash (RS-01); stopping guard prevents overwrite (RS-02); restart awaits exit (RS-03); `done.wait()` times out after 5s; zero `time.sleep()` in focus capture. |
| **Slice 1** | `uv run pytest tests/tier1_pure/`<br>`uv run ruff check .` | Tier 1 passes in < 3.0s with `../nvda` checkout removed; zero AST violations in pure modules; zero Ruff `TID251` violations. |
| **Slice 2** | `uv run pytest tests/tier1_pure/job/` | All valid FSM transitions succeed; invalid transitions raise `IllegalStateTransitionError`; JSON round-trip matches schema; DTOs are frozen. |
| **Slice 3** | `uv run pytest tests/tier2_worker/test_lifecycle.py tests/tier2_worker/test_transport.py` | Worker process spawns under Job Object; pipe handshake negotiates capabilities; broken pipe detected in < 5ms; circuit breaker trips after 3 crashes in 60s. |
| **Slice 4** | `uv run pytest tests/tier2_worker/test_download_executor.py` | Chunked download emits `JobUpdate` every 250ms; HTTP Range resumes partial file; SHA-256 verifies; atomic rename succeeds; cancel deletes temp files. |
| **Slice 5** | `uv run pytest tests/tier1_pure/model_management/` | Non-blocking readiness returns immediately with zero sockets; missing model returns `MODEL_UNAVAILABLE` without mutating config; negative visibility filters correctly. |
| **Slice 6** | `uv run pytest tests/tier2_worker/test_litert_worker.py` | LiteRT server process owned and supervised by Worker; LiteRT crash does not impact NVDA; health polling functions over loopback. |
| **Slice 7** | `uv run pytest tests/tier2_worker/test_llama_worker.py` | llama-server process owned and supervised by Worker; preset generation executed in Worker; model switching operates cleanly. |
| **Slice 8** | `uv run pytest tests/integration/test_clean_concurrency.py` | Zero daemon threads spawned on NVDA exit; `_TestShimSupervisor` removed; `plugin/background.py` contains zero execution logic. |
| **Slice 9** | `uv run pytest tests/tier2_worker/test_ocr_streaming.py` | 30 FPS screen capture fed to OCR engine: queue depth $\le 2$ at all times; older unstarted frames dropped; zero latency lag or memory growth. |
| **Slice 10**| `uv run pytest tests/tier2_worker/test_transcription_streaming.py`| Audio capture fed to ring buffer: memory capped at 320 KB; partial hypotheses emitted < 200ms; finalized emitted on silence boundary; zero capture thread stalls. |

---

## 19. Rollback Points & Reversibility

Each migration slice is designed as an atomic, independently reversible unit of work:

| Slice | Git Rollback Tag | Reversibility Procedure | Data & Config Compatibility Impact |
| :--- | :--- | :--- | :--- |
| **Slice 0** | `rollback-slice-0` | `git revert HEAD~N..HEAD` in `runtime_supervisor/` and `image/focus_capture.py` | Zero config impact. Pure bug fixes. |
| **Slice 1** | `rollback-slice-1` | Restore `conftest.py` and logger imports via `git checkout rollback-slice-1` | Zero config impact. Test & import reorganization only. |
| **Slice 2** | `rollback-slice-2` | Remove `core/job/` package; restore `navigation_context` | In-memory DTOs; zero persistent state impact. |
| **Slice 3** | `rollback-slice-3` | Revert `plugin/application.py` worker initialization; stop worker launcher | Worker named pipes closed; zero config impact. |
| **Slice 4** | `rollback-slice-4` | Revert download client; restore in-process `download.py` execution | Downloads in progress retain `.part` files; resume-compatible. |
| **Slice 5** | `rollback-slice-5` | Restore `service/model_cache.py`; restore legacy `models/` layout | `inventory.json` is backward-compatible; files retained in subdirectories. |
| **Slice 6** | `rollback-slice-6` | Revert LiteRT supervisor ownership to NVDA-side `server.py` | Ports 9379 re-bound by NVDA in-process supervisor. |
| **Slice 7** | `rollback-slice-7` | Revert llama.cpp supervisor ownership to NVDA-side `llama_server.py` | Port 8080 re-bound by NVDA in-process supervisor. |
| **Slice 8** | `rollback-slice-8` | Restore legacy `plugin/background.py` threading | Concurrency rollback only; zero data loss. |
| **Slice 9** | `rollback-slice-9` | Disable OCR continuous session registration | Video/screen OCR feature flag disabled; chat unaffected. |
| **Slice 10**| `rollback-slice-10`| Disable Transcription continuous session registration | Audio transcription feature flag disabled; chat unaffected. |

---

## 20. Packaging Implications (.nvda-addon, SCons, Wheels)

### 20.1 Defense-in-Depth Packaging Integrity (Invariant A28)
1. **SCons Exclusion Rules (`site_scons/site_tools/NVDATool/addon.py`)**:
   Packaging rules must preserve defense-in-depth exclusions:
   - Zero test files (`test_*.py`, `conftest.py`, `tests/` directories).
   - Zero pytest configuration or fixtures.
   - Zero Python bytecode (`*.pyc`, `__pycache__`).
2. **Binary Artifact Placement**:
   - `nvda_ui_host.exe`: Placed in `addon/globalPlugins/AI-assistant/ui_host/nvda_ui_host.exe`.
   - `ai_assistant_worker.exe` (or worker launcher): Placed in `addon/globalPlugins/AI-assistant/worker/ai_assistant_worker.exe`.
   - Native PyO3 extensions (`runtime_supervisor.pyd`, `embedding_engine.pyd`, `llm_client.pyd`, `memory_engine.pyd`): Bundled inside the Worker directory (`worker/lib/`), completely removed from the NVDA-loaded `addon/.../lib/` path.
3. **Build Graph Verification**:
   - `uv run scons --dry-run` must evaluate the complete package graph with zero errors.
   - Full packaging command: `uv run scons`.

---

## 21. Worker & Runtime Recovery Strategy

### 21.1 Recovery State Machine & Generation Epochs (Invariants A19, A20)

```
        +------------------+
        |  WORKER_RUNNING  |
        +------------------+
                 |
                 | Pipe Broken (ERROR_BROKEN_PIPE) / Exit Detected
                 v
        +------------------+
        | WORKER_CRASHED   | ---> Increment active_generation
        +------------------+      Fail active jobs (retriable=True)
                 |
                 v Sliding Window Check (crashes in 60s)
         +---------------+---------------+
         | < 3 crashes   | >= 3 crashes  |
         v               v               v
+------------------+           +----------------------+
| RESTARTING       |           | FAILED_TRIPPED       | (Circuit Breaker)
| (Exp Backoff)    |           | - Halt auto-restart  |
+------------------+           | - Alert user via TTS |
         |                     +----------------------+
         v Spawns new process             |
+------------------+                      | User clicks "Restart Worker"
| HANDSHAKE_INIT   |                      v
+------------------+           +----------------------+
         |                     | RESTARTING (Manual)  |
         v Success             +----------------------+
+------------------+
|  WORKER_RUNNING  |
+------------------+
```

1. **Generation Increment**: On crash or disconnect, `active_generation` increments immediately. Any late responses or zombie IPC frames are discarded.
2. **Circuit Breaker Policy**: If the worker crashes $\ge 3$ times within 60 seconds, state transitions to `FAILED_TRIPPED`. Auto-restart halts. NVDA announces: *"AI Assistant local worker stopped responding. Model features unavailable. Open Settings to restart or view diagnostics."*
3. **Port Contention Recovery**: If a newly spawned worker finds port 9379 or 8080 bound, the worker's native supervisor queries the OS network table (`GetExtendedTcpTable`), discovers the zombie PID, forcefully terminates it, and re-binds cleanly.

---

## 22. Accessibility Impact & Responsiveness Guarantees

### 22.1 Speech & Braille Priority Invariant (Invariants A1–A4, A27)
1. **Sub-50ms Handoff**: Gesture triggers capture immutable DOM/image snapshots on the NVDA thread in < 5 ms and hand off immediately to Worker IPC.
2. **Zero Audio Stutter**: Complete elimination of main-thread `time.sleep()`, synchronous socket I/O, and CPU-intensive PNG compression ensures audio synthesis and braille display updates are never interrupted.
3. **Speech Interruption & Ducking (Slice 10)**: During continuous audio dictation, NVDA audio output can be ducked or muted via acoustic echo cancellation filters to prevent TTS output from bleeding into the transcription microphone.
4. **Screen Curtain Compatibility**: `image/screen_curtain.py:31` fail-fast check ensures image captures are skipped immediately if the screen curtain is active, protecting user privacy.

---

## 23. Performance & Resource Limits

### 23.1 CPU & Process Scheduling Bounds
- **Worker Process Priority**: Configured with `BELOW_NORMAL_PRIORITY_CLASS`. NVDA runs at `HIGH_PRIORITY_CLASS`. Heavy background LLM inference or model unpacking will never starve NVDA's accessibility event loop of CPU cycles.
- **Worker Thread Pool**: Thread pool executor bounded to `min(4, os.cpu_count())` workers.

### 23.2 Memory & Queue Capacity Limits (Invariant A29)
- **OCR Bounded Queue**: Max depth $N=2$ (Slot 0 Active, Slot 1 Pending). Memory strictly bounded to 2 uncompressed bitmaps (~16 MB).
- **Audio Ring Buffer**: 10.0-second circular buffer (320 KB for 16 kHz 16-bit PCM). Fixed memory footprint.
- **IPC Command Queues**: In-memory queues bounded to `maxsize = 100`. Backpressure applies to producer when full.
- **IPC Max Frame Size**: 16 MB limit on individual control frames.

---

## 24. Master Catalog of Risks, Blockers & Classified Findings

Every finding, vulnerability, and architectural risk identified across all audits is consolidated below with mandatory classification tags:

| Finding ID | Classification | Location in HEAD (`ced1cbc`) | Description | Target Mitigation Slice |
|---|---|---|---|---|
| **TA-01** | **CONFIRMED, BLOCKER** | `image/focus_capture.py:107–124` | Synchronous `time.sleep(0.1)` retry loop on NVDA main thread freezes event loop for up to 400 ms. | Slice 0 |
| **TA-02** | **CONFIRMED, BLOCKER** | `context/types.py:78`, `presenter.py:422` | Live NVDA COM object leakage via `navigation_context` causes `RPC_E_DISCONNECTED` crashes. | Slice 2 |
| **TA-03** | **CONFIRMED, BLOCKER** | `image/services.py:48–51`, `focus_capture.py:259`| Heavy PIL PNG compression executed synchronously on NVDA main thread (50–250 ms freeze). | Slice 0, Slice 4 |
| **TA-04** | **CONFIRMED, BLOCKER** | `ui/nvda_ui.py:163, 175` | Unbounded `done.wait()` in `nvda_ui.call()` hangs calling threads indefinitely if event queue stalls. | Slice 0 |
| **TA-05** | **CONFIRMED, BLOCKER** | `service/model_cache.py:109–121, 410–413` | Synchronous HTTP network fetch on cache miss blocks calling thread (10–30s freeze). | Slice 5 |
| **TA-06** | **CONFIRMED, BLOCKER** | `plugin/application.py:178, 186`, `background.py:80`| Proliferation of 15+ ad-hoc unmanaged daemon threads causes shutdown races and socket collisions. | Slice 8 |
| **TA-07** | **CONFIRMED, DESIGN DETAIL** | `ui/adapter.py:410` | Direct call to `nvda_ui.message()` from secondary thread bypasses NVDA thread serialization. | Slice 0 |
| **TA-08** | **CONFIRMED, DESIGN DETAIL** | `context/extractors/browser_field_parser.py:32` | Full-DOM virtual buffer parsing on main thread causes 100–300 ms latency spike on large pages. | Slice 0 |
| **TA-09** | **CONFIRMED, DESIGN DETAIL** | `ui/host_process.py:141–148` | Synchronous `Popen.wait(5)` in `stop_host()` delays NVDA plugin shutdown by up to 5 seconds. | Slice 3 |
| **TA-10** | **CONFIRMED, DESIGN DETAIL** | `plugin/background.py:357`, `ui/task_runner.py:52`| Dual competing `BackgroundTaskRunner` classes create fragmented concurrency abstractions. | Slice 8 |
| **TA-11** | **CONFIRMED, BLOCKER** | `providers/runtime/server.py:42`, `llama_server.py:291`| Local runtime process supervision hosted in NVDA rather than Worker process. | Slice 6, Slice 7 |
| **RS-01** | **CONFIRMED, BLOCKER** | `runtime_supervisor/src/supervisor.rs:130–141` | Generation counter fails to increment on child crash or timeout, breaking generation fencing. | Slice 0 |
| **RS-02** | **CONFIRMED, BLOCKER** | `runtime_supervisor/src/supervisor.rs:168–275` | Missing `Stopping` guard in `ensure_ready` causes state overwrite and orphaned zombie child processes. | Slice 0 |
| **RS-03** | **CONFIRMED, BLOCKER** | `runtime_supervisor/src/supervisor.rs:448–467` | `restart()` does not await process exit before spawning, causing socket collisions (`WSAEADDRINUSE`). | Slice 0 |
| **RS-04** | **CONFIRMED, BLOCKER** | `runtime_supervisor/src/supervisor.rs:223–269` | Concurrent conflicting `ensure_ready` calls enter ping-pong livelock loop. | Slice 0 |
| **RS-05** | **CONFIRMED, LIKELY** | `runtime_supervisor/src/health.rs:32–63` | Adopted server configuration trap & model identity blindness (unrelated models adopted blindly). | Slice 0 |
| **RS-06** | **CONFIRMED, DESIGN DETAIL** | `runtime_supervisor/src/process.rs:27–56` | Absence of Windows Job Objects permits process tree leaks on abnormal parent termination. | Slice 0, Slice 3 |
| **RS-07** | **CONFIRMED, DESIGN DETAIL** | `runtime_supervisor/src/process.rs:76–80` | Immediate forceful kill (`TerminateProcess`) bypasses graceful teardown. | Slice 0 |
| **RS-08** | **CONFIRMED, DESIGN DETAIL** | `runtime_supervisor/src/process.rs:44–45` | Complete discard of child `stderr` conceals native CUDA/DLL diagnostics. | Slice 0, Slice 3 |
| **RS-09** | **CONFIRMED, DESIGN DETAIL** | `runtime_supervisor/src/lib.rs:90, 119` | Generic PyO3 `RuntimeError` mapping forces fragile string scraping in Python. | Slice 0 |
| **RS-10** | **CONFIRMED, BLOCKER** | `server.py:322–415`, `llama_server.py:191–258` | Duplicate Python test shims in production modules violate Invariant A7. | Slice 8 |
| **RS-11** | **CONFIRMED, DESIGN DETAIL** | `runtime_supervisor/Cargo.toml:11` | Python 3.14 build environment requires ABI3 forward compatibility flag. | Slice 0 |
| **RS-12** | **CONFIRMED, DESIGN DETAIL** | `runtime_supervisor/src/lib.rs:80–89` | GIL release verified correct across all blocking operations. | N/A (Confirmed Safe) |
| **RS-13** | **CONFIRMED, BLOCKER** | `plugin/background.py:51–112` | Runtime supervisor located in NVDA process rather than Worker boundary. | Slice 6, Slice 7 |
| **F-D01** | **CONFIRMED, BLOCKER** | `conftest.py:27–31` | Root `conftest.py` unconditionally requires sibling `../nvda` checkout before test collection. | Slice 1 |
| **F-D04** | **CONFIRMED, DESIGN DETAIL** | `addon/globalPlugins/AI-assistant/` | Top-level package name collisions (`config`, `core`, `ui`, `utils`) with NVDA source modules. | Slice 1 |
| **F-D05** | **CONFIRMED, DESIGN DETAIL** | `tests/support/bootstrap.py` | Directory hyphen forces synthetic dynamic package bootstrap in all 59 test files. | Slice 1 |
| **F-D06** | **CONFIRMED, BLOCKER** | 18 domain/service files | Direct import of `from logHandler import log` prevents pure-Python execution. | Slice 1 |
| **F-D07** | **CONFIRMED, BLOCKER** | `config/settings.py:8, 200` | Direct import of `import languageHandler` contaminates central configuration. | Slice 1 |
| **F-D08** | **CONFIRMED, DESIGN DETAIL** | `tests/integration/test_nvda_runtime.py` | Fragility of live COM integration tests due to `oleacc.dll` timestamp mismatch in comtypes wrapper. | Slice 1 |
| **F-D09** | **CONFIRMED, DESIGN DETAIL** | Host environment | Python 3.14 on system PATH breaks direct `cargo test` unless run via `uv run cargo test`. | Slice 0 |
| **F-F01** | **CONFIRMED, BLOCKER** | `service/model_cache.py`, `model_manager.py` | Model state fractured across 6 incompatible, non-interoperable enums and structs. | Slice 5 |
| **F-F03** | **CONFIRMED, BLOCKER** | `plugin/background.py:183–196` | Silent configuration mutation & model fallback violates Invariant A14 (Zero Silent Fallbacks). | Slice 5, Slice 8 |
| **F-F04** | **CONFIRMED, BLOCKER** | `service/provider_readiness.py:172–210` | False-positive readiness on cold cache bypasses download check and causes inference crashes. | Slice 5 |
| **F-F06** | **CONFIRMED, DESIGN DETAIL** | `models/litert-lm/`, `models/llama-cpp/` | Divergent disk cache layouts without a unified authoritative inventory manifest. | Slice 5 |
| **F-F08** | **CONFIRMED, DESIGN DETAIL** | `settings_panel.py:182–184` | Negative visibility filtering duplication and leaks forceful re-injection of disabled models. | Slice 5 |
| **FW-01** | **CONFIRMED, BLOCKER** | `providers/runtime/download.py:77–160` | In-process multi-gigabyte downloads and SHA-256 hashing violate thin NVDA shell (Invariant A1). | Slice 4 |
| **FW-02** | **CONFIRMED, BLOCKER** | Theoretical Worker Process | Absence of Windows Job Objects permits orphaned child processes on abnormal NVDA exit. | Slice 3 |
| **FW-03** | **CONFIRMED, BLOCKER** | Continuous streaming in Slices 9 & 10 | Unbounded queueing in continuous modalities causes memory exhaustion and latency lag. | Slice 9, Slice 10 |
| **FW-04** | **CONFIRMED, DESIGN DETAIL** | Native C loops in llama/whisper | Cooperative cancellation token cannot interrupt non-yielding native C loops. | Slice 2, Slice 3 |
| **FW-05** | **CONFIRMED, DESIGN DETAIL** | Named pipe creation | Default named pipe DACL permissions allow unauthorized local processes to connect. | Slice 3 |
| **FW-06** | **CONFIRMED, DESIGN DETAIL** | Frame encoding | NDJSON base64 encoding for 30 FPS video frames incurs 33% CPU/memory overhead. | Slice 9, Slice 10 |
| **FW-07** | **CONFIRMED, BLOCKER** | Worker crash recovery | Stale generation overwrites race with dying processes during recovery. | Slice 3 |
| **FW-08** | **LIKELY, DESIGN DETAIL** | Driver / Hardware incompatibility | Worker crashing repeatedly enters restart loop without circuit breaker. | Slice 3 |
| **FW-09** | **UNKNOWN / REQUIRES EXPERIMENT**| High-resolution screen capture | Windows Named Pipe throughput limits for raw 1080p 30 FPS video (~240 MB/s). | Slice 9 |
| **FW-10** | **LIKELY, DESIGN DETAIL** | Screen reader speech leakage | Screen reader TTS speech leaking into microphone triggers false VAD activations. | Slice 10 |

---

## 25. Architectural Invariant Traceability Matrix (Invariants A1–A30)

| Invariant | Title & Architectural Mandate | Section Citation | Enforcement Mechanism & Verification Gate |
| :--- | :--- | :--- | :--- |
| **A1** | NVDA as a Thin Accessibility Shell | Sec. 1.2, 2.1, 5.1 | All compute, model execution, downloads, and inference isolated out-of-process. Main thread strictly handles accessibility I/O. |
| **A2** | NVDA Main Thread Latency Constraint (< 50ms) | Sec. 5.3, 22.1 | Zero sleeps (`focus_capture.py`), zero synchronous sockets, zero PIL PNG compression on main thread. Immediate fallback. |
| **A3** | NVDA Object-Model Access Thread Affinity | Sec. 5.1, 5.3 | All focus, caret, and virtual buffer calls execute strictly on NVDA event thread via `ui/nvda_ui.py` wrappers. |
| **A4** | Thread-Detached Immutable Snapshots | Sec. 5.3, 15.1 | Zero live COM pointers (`NVDAObject`, `TreeInterceptor`) cross thread boundaries. Replaced by `TargetNavigationSpec` DTO. |
| **A5** | Pure-Python Domain & Service Isolation | Sec. 4.1, 6.2 | 80.7% of codebase decoupled into pure Python. Zero NVDA imports in `core/`, `config/`, `service/`, `providers/`, `use_case/`. |
| **A6** | Automated Import Boundary Enforcement | Sec. 6.3 | Ruff `TID251` banned API rules + automated AST test gate (`test_import_boundaries.py`) in Tier 1 CI. |
| **A7** | Native Supervisor Authoritative Ownership | Sec. 8.1, 8.2 | Rust `runtime_supervisor` is the sole owner of runtime mechanics. Production Python test shims (RS-10) completely deleted. |
| **A8** | Immutable Runtime Specifications | Sec. 8.1, 12.2 | Typed `RuntimeSpec` DTO with deterministic hashing. No ad-hoc parameter mutation during execution. |
| **A9** | Generation Fencing across Epochs | Sec. 3.5, 8.1, 14.4| Monotonic integer generation counter increments on all crashes, timeouts, and restarts (RS-01 to RS-04 fixed). Stale updates dropped. |
| **A10** | Clean PyO3 FFI Boundary | Sec. 8.1, 8.2 | GIL released during all blocking operations (`py.allow_threads`). Native typed exception hierarchy exposed. |
| **A11** | Unified Model Registry across Multi-Modalities | Sec. 12.1, 12.2 | Single immutable `ModelDescriptor` and `Modality` enum for CHAT, VISION, OCR, TRANSCRIPTION, EMBEDDING, TTS. |
| **A12** | Centralized Download State Machine | Sec. 12.1, 17 (Sl 4)| Out-of-process Worker execution, HTTP Range resume, streaming SHA-256 hashing, atomic staging swaps. |
| **A13** | Standardized Disk Storage Layout | Sec. 12.1, 17 (Sl 5)| Unified `%APPDATA%/.../models/` tree with `inventory.json` manifest. User-owned files strictly protected. |
| **A14** | Non-Blocking Readiness & Zero Silent Fallbacks| Sec. 12.1, 12.3| Zero network sockets on `evaluate()`. Fail-closed policy: missing models report `MODEL_UNAVAILABLE`; zero silent config mutation. |
| **A15** | Multi-Modal Resource Arbitration Engine | Sec. 12.3 | Hardware budget tiers (Low/Mid/High). Cooperative GPU execution queue. 60s idle reaper for one-shot vision/OCR models. |
| **A16** | Worker Process Isolation | Sec. 2.1, 2.3, 14.1| Worker runs in dedicated Win32 process wrapped in Windows Job Object (`KILL_ON_JOB_CLOSE`). Native crashes isolated. |
| **A17** | Versioned Handshake & Capability Negotiation | Sec. 14.1, 16.1| Semantic versioning (`1.0.0`) handshake over named pipe. Capability negotiation required before work dispatch. |
| **A18** | Framing & Transport Integrity | Sec. 14.2, 14.3| Bi-directional Named Pipes with Win32 DACLs (user SID). NDJSON control plane (16 MB) + 2-part hybrid binary streaming frame. |
| **A19** | Heartbeat, Liveness & Crash Detection | Sec. 3.4, 14.4| 5s heartbeat probe, 15s timeout. Broken pipe detected in < 5ms. Process exit status captured. |
| **A20** | Graceful Restart & Circuit Breaker | Sec. 3.6, 21.1| Exponential backoff restart. Circuit breaker trips after $\ge 3$ crashes in 60s (`FAILED_TRIPPED`), halting restart loop. |
| **A21** | Discrete Job Finite State Machine | Sec. 15.1 | Monotonic progression: `SUBMITTED` -> `QUEUED` -> `RUNNING` -> terminal `COMPLETED`/`FAILED`/`CANCELLED`. Single result emitted. |
| **A22** | Deterministic Two-Phase Cancellation | Sec. 15.2 | Phase 1: Cooperative token check at yield points (64 KB / tokens). Phase 2: 3.0s supervisor preemption & worker recycle. |
| **A23** | Continuous Session Finite State Machine | Sec. 15.3 | State machine: `INIT` -> `CONFIGURING` -> `READY` <-> `STREAMING` <-> `PAUSED` -> `CLOSING` -> `CLOSED`. Multi-session multiplexing. |
| **A24** | Immutable DTO Definitions & Schemas | Sec. 16.1, 16.2| Frozen dataclasses with slots and JSON schemas (Draft 2020-12) for all 8 IPC envelopes. |
| **A25** | Process Isolation within Worker Boundary | Sec. 2.1, 17 (Sl 6-7)| LiteRT and llama-server owned and supervised directly by Worker process, not NVDA. |
| **A26** | Rust Runtime Supervisor Process Mechanics | Sec. 8.1, 8.2 | Clean termination, Windows Job Object containment, 64 KB `stderr` diagnostic ring buffer. |
| **A27** | Non-Blocking Output Marshaling | Sec. 5.1, 22.1 | All presentation events marshaled onto NVDA event queue via `queueHandler.queueFunction`. Never block on GUI. |
| **A28** | Packaging Integrity & Defense-in-Depth | Sec. 20.1 | `.nvda-addon` excludes all tests, pytest files, bytecode. Bundles worker and native `.pyd`s in worker subdirectory. |
| **A29** | Bounded Streaming for Continuous Modalities | Sec. 15.4 | OCR bounded queue ($N=2$) with latest-wins dropping; Audio transcription 10s circular ring buffer with partial/finalized transcripts. |
| **A30** | Decoupled Three-Tier Test Architecture | Sec. 7.1, 7.2 | Tier 1 (Pure Python < 3s, zero NVDA), Tier 2 (Rust/Worker < 8s), Tier 3 (NVDA Integration ~15s). |

---

*End of Pre-Implementation Architectural Deliverable.*
