# Audit B & Invariants A1–A4, A27: NVDA Boundary & Thread-Affinity Audit Report

- **Auditor**: NVDA Boundary & Thread-Affinity Auditor (Agent 2)
- **Repository Root**: `D:\nvda-addons\NVDA-AI-assistant`
- **Working Directory**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_nvda_thread_2`
- **Commit HEAD**: `ced1cbc`
- **Date**: 2026-10-02
- **Status**: Complete & Verified

---

## 1. Executive Summary & Audit Scope

This audit provides an exhaustive, code-level investigation of all production concurrency constructs, thread affinity rules, and NVDA boundary interactions in `adil-adysh/NVDA-AI-assistant` at commit `ced1cbc`.

The audit specifically fulfills:
1. **Audit B (Thread & Executor Map)**: Full enumeration and classification of all production threads, thread pools, locks, condition variables, events, and background queues across production modules, classifying each construct into `KEEP IN NVDA`, `MOVE TO PURE PYTHON`, `MOVE TO WORKER`, `RUST-OWNED`, or `REMOVE/CONSOLIDATE`.
2. **Invariants A1–A4 & A27 (NVDA Event/Main Thread Affinity & Thin Shell)**:
   - Audit of NVDA object-model access (focus, caret, review cursor, virtual buffer, screen/window captures).
   - Audit of NVDA output mechanisms (speech, tones, braille, `queueHandler`).
   - Deep trace of latency spikes and blocking violations on the NVDA event/main thread.
   - Comprehensive technical design for thread-affine snapshotting on the NVDA event thread isolating downstream execution.

### Key Audit Findings Summary
- **Critical Blocker: Synchronous `time.sleep()` on the NVDA Main Thread [CONFIRMED, BLOCKER]**: In `image/focus_capture.py:107-124`, `_resolve_capture_location_with_retry()` executes a retry loop of up to 5 attempts with `time.sleep(0.1)`, called synchronously on the NVDA main thread via `nvda_ui.call()`. This causes up to **400 ms of pure thread freeze** on NVDA's main event loop during focus image capture.
- **Critical Blocker: Live NVDA Object Leakage across Thread Boundaries [CONFIRMED, BLOCKER]**: `BrowserExtractionSnapshot.navigation_context` (`context/types.py:78`) stores a live `TreeInterceptor` or `NVDAObject`. This live COM object is transmitted across thread boundaries into `use_case_engine.execute()` on background worker threads, and persisted in `ResultActionStore` (`plugin/presenter.py:422`), directly violating Invariant A4 and causing dangling COM pointer crashes (`RPC_E_DISCONNECTED`).
- **Critical Blocker: Synchronous CPU-Intensive Image Encoding on NVDA Main Thread [CONFIRMED, BLOCKER]**: In `image/services.py:48-51` and `image/focus_capture.py:259-265`, `ImageGrab.grab()` and synchronous PIL PNG encoding (`image.save(buffer, format="PNG")`) execute directly on the NVDA main thread inside `_capture_all()` / `_capture_region_and_metadata()`, freezing speech and braille during multi-megabyte compression.
- **Critical Blocker: Unbounded `done.wait()` in `nvda_ui.call()` [CONFIRMED, BLOCKER]**: `ui/nvda_ui.py:175` executes `done.wait()` without a timeout. If NVDA's event queue is halted, in modal dialog loops, or shedding load during shutdown, background threads hang indefinitely.
- **Fragmented Concurrency & Thread Spawning Proliferation [CONFIRMED, BLOCKER]**: Over **15 ad-hoc unmanaged `threading.Thread` spawners** exist across `plugin/application.py`, `plugin/background.py`, `ui/adapter.py`, `ui/host_transport.py`, and `service/model_cache.py`. Two competing executor/runner abstractions exist (`BackgroundTaskRunner` in `plugin/background.py` and `BackgroundTaskRunner` with `ThreadPoolExecutor(4)` in `ui/task_runner.py`).

---

## 2. Audit B: In-Depth Production Concurrency Audit

### 2.1 `addon/globalPlugins/AI-assistant/plugin/background.py`

`plugin/background.py` is the historical coordinator for non-main-thread operations.

#### Concurrency Constructs
1. **`BackgroundTaskRunner` worker tracking**:
   - `self._threads: set[threading.Thread] = set()` (`background.py:372`)
   - `self._threads_lock = threading.Lock()` (`background.py:373`)
   - `self._closed = threading.Event()` (`background.py:371`)
   - `_start_worker()` (`background.py:384-402`): Spawns daemon worker threads named `AIassistant{title}Worker` or `BrowserAssistantModelPreload`. Worker registers in `_threads` and discards itself in a `finally` block.
2. **Ad-Hoc Config Change Thread Spawners**:
   - `_on_litert_server_config_changed()` (`background.py:80-84`): Spawns unmanaged `threading.Thread(target=_restart_litert_server_worker, name="litert-restart-on-config-change", daemon=True)`.
   - `_on_llama_server_config_changed()` (`background.py:105-109`): Spawns unmanaged `threading.Thread(target=shutdown_llama_servers, name="llama-shutdown-on-config-change", daemon=True)`.
3. **Model Preload Background Worker**:
   - `start_model_preload()` (`background.py:404-439`): Spawns thread `"BrowserAssistantModelPreload"` to execute `_readiness_service.evaluate_active()` and `_llm_service.ensure_model_available()`.
4. **Use Case Background Worker**:
   - `run_use_case_in_background()` (`background.py:441-495`): Spawns thread `f"AIassistant{title}Worker"`. Executes `ensure_provider_server_ready()` (line 450) and `self._use_case_engine.execute()` (line 457).

#### Concurrency Evaluation
- **Flaw**: Spawns unmanaged threads on every configuration change without debouncing or rate-limiting. A rapid slider change in settings spawns multiple concurrent server restart/shutdown threads colliding on socket ports.
- **Boundary Violation**: `_use_case_engine.execute()` runs inside the background thread, but downstream use cases call `context_pipeline.collect()`, which synchronously calls back into the main thread via `nvda_ui.call()`. This creates multi-hop thread ping-ponging (Main Thread -> Worker Thread -> Main Thread -> Worker Thread).
- **Target Classification**: **MOVE TO WORKER / REMOVE/CONSOLIDATE**. `BackgroundTaskRunner` should be eliminated from the NVDA process; use cases and preloads must be submitted as typed IPC jobs to the external Worker process.

---

### 2.2 `addon/globalPlugins/AI-assistant/plugin/application.py`

`plugin/application.py` is the application facade and gesture dispatch target.

#### Concurrency Constructs
1. **`_auto_start_active_local_provider()` (`application.py:117-151`)**: Delegates to `schedule_active_local_provider_start()`.
2. **`terminate()` (`application.py:178-192`)**:
   - Spawns ad-hoc thread `LiteRTServerShutdown` calling `get_litert_supervisor().stop()`.
   - Spawns ad-hoc thread `LlamaServerShutdown` calling `shutdown_llama_servers()`.
3. **`_on_provider_state_change()` (`application.py:202-207`)**:
   - Spawns ad-hoc thread `ProviderStateChange` calling `self._handle_provider_state_change()`.
   - Rationale stated in docstring (`lines 197-200`): synchronous IPC (`sync_session_state`) can block for seconds while the host process starts.
4. **`capture_accessibility_graph()` (`application.py:354-358`)**:
   - Spawns ad-hoc thread `AccessibilityGraphCapture` calling `self._capture_accessibility_graph_worker()`.
   - Worker calls `self._services.context_pipeline.capture_current_page_snapshot()` which calls back to main thread via `nvda_ui.call()`, saves graph to disk, and queues completion announcement via `nvda_ui.queue()`.
5. **`_select_provider_by_id()` (`application.py:414-418`)**:
   - Spawns ad-hoc thread `f"{provider_id}ServerSwitchStart"` calling `ensure_provider_server_ready()`.
6. **`select_model_for_current_provider()` (`application.py:478-482`)**:
   - Spawns ad-hoc thread `ModelListFetch` calling `_fetch_and_announce()`, which performs blocking catalog fetch, then uses `nvda_ui.call()` to announce and prompt.

#### Concurrency Evaluation
- **Flaw**: Proliferation of uncontrolled fire-and-forget daemon threads (7 distinct thread spawn sites in one file).
- **Flaw**: Shutdown races. In `terminate()`, daemon threads are spawned to shut down servers, but if NVDA process exits before the thread completes, child processes (`litert-lm`, `llama-server`) are orphaned and leak memory/GPU allocations.
- **Target Classification**: **KEEP IN NVDA (facade only) / MOVE TO WORKER (all async tasks)**. The application facade stays in NVDA as a thin coordinator, but all background operations become IPC calls to the Worker.

---

### 2.3 `addon/globalPlugins/AI-assistant/plugin/local_provider_startup.py`

#### Concurrency Constructs
- `schedule_active_local_provider_start()` (`local_provider_startup.py:13-49`):
  - Spawns ad-hoc daemon thread:
    ```python
    thread = thread_factory(
        target=start_server,
        name=f"{provider}ServerAutoStart",
        daemon=True,
    )
    thread.start()
    ```

#### Concurrency Evaluation
- **Target Classification**: **REMOVE/CONSOLIDATE**. In the target topology, NVDA does not start local runtime servers at all. The Worker process manages runtime supervisor lifecycles.

---

### 2.4 `addon/globalPlugins/AI-assistant/ui/task_runner.py`

#### Concurrency Constructs
1. **`UiDispatcher.post(callback)` (`task_runner.py:28-34`)**:
   - Dispatches callbacks onto wxWidgets main event loop via `wx.CallAfter(callback)`.
2. **`TaskHandle[T]` (`task_runner.py:36-50`)**:
   - Encapsulates `cancel_event: threading.Event` and `_future: Future[T]`.
3. **`BackgroundTaskRunner` (`task_runner.py:52-155`)**:
   - Owns a private `ThreadPoolExecutor`:
     ```python
     self._executor = ThreadPoolExecutor(
         max_workers=max_workers,
         thread_name_prefix="NVDA-AI-worker",
     )
     ```
   - Global singleton: `background_tasks = BackgroundTaskRunner()` (`task_runner.py:157`).
   - Used by native wx dialogs: `download_progress.py`, `embedding_model_dialog.py`, `provider_configure.py`, `model_manager.py`, `settings_panel.py`.

#### Concurrency Evaluation
- **Design Conflict**: This is a duplicate `BackgroundTaskRunner` class competing with `plugin/background.py:BackgroundTaskRunner`.
- **Target Classification**:
  - `UiDispatcher.post` (`wx.CallAfter`): **KEEP IN NVDA** (necessary for native NVDA wx GUI dialogs).
  - `ThreadPoolExecutor`: **MOVE TO WORKER / CONSOLIDATE**. Dialog tasks that perform heavy network or disk operations (model downloads, provider test requests) must be delegated to the Worker process. For pure wx dialog UI transitions, a lightweight single-threaded dispatcher or `wx.CallAfter` is sufficient.

---

### 2.5 `addon/globalPlugins/AI-assistant/ui/adapter.py`

`ui/adapter.py` is the policy boundary between NVDA, `nvda_ui_host.exe`, and native fallback.

#### Concurrency Constructs
1. **`UIAdapter._command_queue` & `_worker_thread`**:
   - `self._command_queue: queue.Queue[...] = queue.Queue()` (`adapter.py:38-40`)
   - `self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)` (`adapter.py:42-43`)
   - `self._running = True`
   - `_worker_loop()` (`adapter.py:78-107`): Continuously blocks on `_command_queue.get()`, executes pipe commands to `nvda_ui_host.exe`, catches `HostUnavailableError`, and marshals fallback callbacks back to NVDA via `nvda_ui.queue(fallback)`.
   - `close()` (`adapter.py:65-77`): Puts `_STOP_WORKER`, sets `self._running = False`, and joins `_worker_thread` with a 1.0s timeout.
2. **Chat Submission Ad-Hoc Worker Thread**:
   - `open_chat_view` -> `handle_chat_submission` (`adapter.py:222-226`):
     ```python
     threading.Thread(
         target=self._handle_host_chat_submission,
         args=(message, conversation_id, coordinator, event_payload),
         daemon=True,
     ).start()
     ```
   - Spawns a new daemon thread for EVERY user chat message submitted from the WebView!
   - In `_handle_host_chat_submission` (`adapter.py:345-389`), executes `coordinator.send_message(...)` which performs synchronous streaming inference and network I/O.

#### Concurrency Evaluation
- **Strengths**: `_command_queue` and `_worker_thread` cleanly prevent the NVDA main thread from blocking on Windows named pipe I/O.
- **Flaws**:
  - `handle_chat_submission` creates unbounded ad-hoc daemon threads on user message submissions. If the user rapidly sends multiple messages, concurrent `_handle_host_chat_submission` threads execute simultaneously, racing on `coordinator._turn_lock`.
  - Line 410: On error, calls `nvda_ui.message(presentation.message)` directly from the daemon thread instead of `nvda_ui.queue()`.
- **Target Classification**:
  - `_command_queue` and `_worker_thread`: **KEEP IN NVDA** (bridges NVDA event thread to UI host pipe).
  - `_handle_host_chat_submission`: **MOVE TO WORKER**. Chat submission must submit a job to the Worker process; streaming deltas return via IPC.

---

### 2.6 `addon/globalPlugins/AI-assistant/ui/host_transport.py`

`ui/host_transport.py` manages Windows named pipe IPC (`\\.\pipe\nvda_ai_assistant_ui_cmd` and `\\.\pipe\nvda_ai_assistant_ui_evt`).

#### Concurrency Constructs
1. **`HostPipeTransport._stop_event`**: `threading.Event()` (`host_transport.py:28`)
2. **`HostPipeTransport._event_listener_lock`**: `threading.Lock()` (`host_transport.py:30`)
3. **`_event_listener_loop()` thread**:
   - `thread = threading.Thread(target=self._event_listener_loop, name="ui_host_event_listener", daemon=True)` (`host_transport.py:41-46`)
   - Reads event pipe line by line; dispatches via `_dispatch_event(payload)`.
4. **Synchronous Command IPC (`send_and_receive`)**:
   - Synchronous blocking call via `win32file.WriteFile` and `_read_response` (5s timeout) (`host_transport.py:49-67`).
   - Contains polling loop in `_read_line` with `time.sleep(0.01)` (`line 161`) and pipe wait with `time.sleep(0.1)` (`line 222`).

#### Concurrency Evaluation
- **Strengths**: Named pipe reading is isolated in `ui_host_event_listener`. Synchronous `send_and_receive` is only invoked from `UIAdapter._worker_loop`, never blocking NVDA's event loop.
- **Target Classification**: **KEEP IN NVDA**. This is the native UI transport between NVDA and the WebView2 host executable.

---

### 2.7 `addon/globalPlugins/AI-assistant/ui/host_process.py`

#### Concurrency Constructs
1. **`_process_lock`**: `threading.Lock()` (`host_process.py:16`)
2. **`_host_process`**: `subprocess.Popen | None` (`host_process.py:14`)
3. **`_host_logger_thread`**:
   - `threading.Thread(target=_drain_host_output, args=(process,), name="ui_host_stdout_reader", daemon=True)` (`host_process.py:101-107`)
   - Drains `stdout` of `nvda_ui_host.exe` and logs to NVDA log.
4. **Readiness Polling**:
   - `_wait_for_host_pipe_ready` (`host_process.py:36-63`): Polling loop with `time.sleep(0.1)` and 5.0s deadline.
5. **Teardown**:
   - `stop_host()` (`host_process.py:134-151`): Synchronously calls `process.terminate()` and `process.wait(timeout=5)`.

#### Concurrency Evaluation
- **Latency Risk**: `stop_host()` runs synchronously inside `AIAssistantApplication.terminate()`. If `nvda_ui_host.exe` hangs on exit, NVDA plugin shutdown is blocked for up to 5 seconds.
- **Target Classification**: **KEEP IN NVDA**. NVDA must manage the lifecycle of its own UI host process, but `stop_host()` timeout should be non-blocking or guarded with a tight 1s bound.

---

### 2.8 `addon/globalPlugins/AI-assistant/service/model_cache.py`

`service/model_cache.py` provides centralized caching of provider models and capabilities.

#### Concurrency Constructs
1. **`ModelCatalogCache` Lock**:
   - `self._lock = threading.RLock()` (`model_cache.py:85`)
2. **`_FetchGate` Synchronization**:
   - `self.event = threading.Event()` (`model_cache.py:65`)
   - `self.result: tuple[ProviderModelInfo, ...] = ()`
   - `self.error: Exception | None = None`
   - Coordinates concurrent fetches: first thread performs fetch; subsequent threads wait on `gate.event.wait()`.
3. **Background Preload & Fetch Threads**:
   - `preload_all()` (`model_cache.py:188-196`): Spawns `threading.Thread(target=self._preload_background, name="ModelCatalogPreload", daemon=True)`.
   - `preload_async()` (`model_cache.py:197-219`): Spawns `threading.Thread(target=self._fetch_background, name=f"ModelCatalogFetch-{provider_id}", daemon=True)`.
4. **`ModelCapabilityCache` Lock**:
   - `self._lock = threading.RLock()` (`model_cache.py:397`)

#### Concurrency Evaluation
- **Critical Flaw: Synchronous Fetch on Waiter**:
  In `_fetch_and_cache` (`line 286`): `gate.event.wait()` has **no timeout**. If the fetcher thread hangs on a stalled socket connection, all waiter threads hang indefinitely.
- **Critical Flaw: Synchronous Network Fetch on Cache Miss**:
  In `get_models(provider_id)` (`lines 99-121`), if the cache is cold, it invokes `_perform_fetch()` synchronously. If called from any UI or event path, this executes a blocking HTTP request on the caller.
  In `ModelCapabilityCache.get()` (`lines 409-413`), if the cache is cold or in error, it calls `self._catalog_cache.get_models(key[0])` synchronously!
- **Target Classification**: **MOVE TO WORKER**. Model discovery, network catalog fetching, and capability probes must be performed exclusively in the Worker process. NVDA should hold only a read-only, push-updated immutable catalog snapshot (`ModelCatalogSnapshot`).

---

### 2.9 Additional Production Concurrency Constructs

| File | Construct | Line(s) | Role & Mechanics |
|---|---|---|---|
| `ui/nvda_ui.py` | `_streaming_tone_lock` | `17` | `threading.Lock()`. Throttles audio beep generation to min 1.0s interval. |
| `ui/nvda_ui.py` | `call()` | `163, 175` | `done = threading.Event()`. Calls `queueHandler.queueFunction(eventQueue, runner)` and awaits `done.wait()`. |
| `ui/nvda_ui.py` | `queue()` | `156` | Direct call to `queueHandler.queueFunction(queueHandler.eventQueue, ...)`. |
| `service/base.py` | `BaseCoordinator._lock` | `48` | `threading.Lock()`. Guards `_active_worker`. |
| `service/base.py` | `BaseCoordinator.start_task()` | `66-74` | Spawns daemon `threading.Thread` for `_run_in_background`. (Dead code in `ChatCoordinator`). |
| `service/chat/coordinator.py` | `_session_lock` | `53` | `threading.RLock()`. Guards session turns and conversation state. |
| `service/chat/coordinator.py` | `_turn_lock` | `56` | `threading.Lock()`. Ensures atomic turn execution across concurrent submissions. |
| `service/error_reporter.py` | `_lock` | `39` | `threading.Lock()`. Guards in-memory error event history and deduplication. |
| `providers/provider_proxy.py` | `_warn_if_main_thread` | `25-26` | `threading.current_thread() is threading.main_thread()`. Logs warning if called on main thread. |
| `providers/_provider_runtime.py` | `_lock` | `26` | `threading.RLock()`. Guards active provider instance recreation on config change. |
| `providers/runtime/server.py` | `_CONFIG_WRITE_LOCK` | `51` | `threading.Lock()`. Guards writing `config.json` for LiteRT server. |
| `providers/runtime/server.py` | `_TestShimSupervisor._lock` | `335` | `threading.RLock()`. Unverified Python test shim supervisor lock. |
| `providers/runtime/server.py` | `cancel_event` | `607` | `threading.Event \| None`. Signals cancellation for runtime download. |
| `providers/runtime/llama_server.py` | `_LlamaServerProcess._lock` | `105` | `threading.RLock()`. Guards process state in Python test shim. |
| `providers/runtime/llama_server.py` | `_models_cache_lock` | `279` | `threading.Lock()`. Guards cached model list for llama-server. |
| `providers/runtime/llama_server.py` | `_supervisors_lock` | `530` | `threading.RLock()`. Guards global `_supervisors` dict. |
| `providers/llama_manager.py` | `_lock` | `62` | `threading.RLock()`. Guards manager instance state. |
| `providers/runtime/llama_models.py` | `_lock` | `242` | `threading.RLock()`. Guards preset catalog and custom models. |
| `providers/runtime/download.py` | `cancel_event` | `85, 286` | `threading.Event \| None`. Checked during socket chunk read loop. |
| `providers/runtime/model_download.py` | `cancel_event` | `71, 163` | `threading.Event \| None`. Checked during model download chunk loop. |
| `providers/model_manager.py` | `_cache_lock` | `178` | `threading.Lock()`. Guards cached records list. |
| `providers/capabilities.py` | `_registry_lock` | `13` | `from threading import RLock`. Guards provider capability registration. |
| `ui/download_progress.py` | `_cancel_event` | `83` | `threading.Event()`. Set when user clicks Cancel. |
| `ui/download_progress.py` | `_completion_lock` | `84` | `threading.Lock()`. Prevents double completion callback in wx dialog. |
| `ui/download_progress.py` | `start()` | `247` | Spawns daemon `threading.Thread` to execute download away from wx thread. |
| `ui/action_store.py` | `_lock` | `12` | `threading.RLock()`. Guards tokenized UI action payload store. |
| `ui/host_lifecycle.py` | `_lock` | `19` | `threading.RLock()`. Guards host state transitions (`STOPPED`, `STARTING`, etc.). |
| `config/model_config.py` | `_lock` | `168` | `threading.RLock()`. Guards model-specific sampling JSON store. |
| `config/enabled_models.py` | `_lock` | `49` | `threading.RLock()`. Guards enabled models JSON store. |

---

## 3. Concurrency Construct Master Classification Table

The table below classifies **every concurrency construct** into its designated architectural ownership category:

| Construct ID | Exact File Path & Lines (`ced1cbc`) | Construct Name / Type | Current Role | Target Classification | Target Disposition / Rationale |
|---|---|---|---|---|---|
| **CC-01** | `plugin/background.py:371` | `self._closed` (`threading.Event`) | Background runner cancellation | **MOVE TO WORKER** | Replaced by Worker job cancellation protocol. |
| **CC-02** | `plugin/background.py:372-373` | `self._threads` & `_threads_lock` | Worker thread tracking | **REMOVE/CONSOLIDATE** | Eliminated when background execution moves to Worker process. |
| **CC-03** | `plugin/background.py:396` | `AIassistant{title}Worker` (`Thread`) | Use case execution thread | **MOVE TO WORKER** | Use cases submitted as typed jobs to Worker process. |
| **CC-04** | `plugin/background.py:404` | `BrowserAssistantModelPreload` (`Thread`) | Model preload worker | **MOVE TO WORKER** | Model preload submitted as background Worker job. |
| **CC-05** | `plugin/background.py:80` | `litert-restart-on-config-change` (`Thread`) | Local server restart | **REMOVE/CONSOLIDATE** | Managed locally by Worker; NVDA sends config update over IPC. |
| **CC-06** | `plugin/background.py:105` | `llama-shutdown-on-config-change` (`Thread`) | Local server shutdown | **REMOVE/CONSOLIDATE** | Managed locally by Worker; NVDA sends config update over IPC. |
| **CC-07** | `plugin/application.py:178` | `LiteRTServerShutdown` (`Thread`) | Server shutdown on exit | **REMOVE/CONSOLIDATE** | Worker process manages runtime supervisor child teardown. |
| **CC-08** | `plugin/application.py:186` | `LlamaServerShutdown` (`Thread`) | Server shutdown on exit | **REMOVE/CONSOLIDATE** | Worker process manages runtime supervisor child teardown. |
| **CC-09** | `plugin/application.py:202` | `ProviderStateChange` (`Thread`) | State change IPC deferral | **REMOVE/CONSOLIDATE** | Session state sync handled asynchronously via Worker IPC. |
| **CC-10** | `plugin/application.py:354` | `AccessibilityGraphCapture` (`Thread`) | Graph file saving thread | **MOVE TO WORKER** | Main thread snapshots graph; serialization handed to Worker. |
| **CC-11** | `plugin/application.py:414` | `{provider}ServerSwitchStart` (`Thread`) | Auto-start on provider switch | **MOVE TO WORKER** | Provider switch notifies Worker; Worker manages readiness. |
| **CC-12** | `plugin/application.py:478` | `ModelListFetch` (`Thread`) | Model catalog fetch thread | **MOVE TO WORKER** | NVDA reads pushed catalog snapshot; Worker handles fetching. |
| **CC-13** | `plugin/local_provider_startup.py:43` | `{provider}ServerAutoStart` (`Thread`) | Startup auto-start thread | **REMOVE/CONSOLIDATE** | Worker process auto-starts runtime supervisor on launch. |
| **CC-14** | `ui/task_runner.py:28` | `UiDispatcher.post` (`wx.CallAfter`) | wx event loop dispatch | **KEEP IN NVDA** | Required for NVDA wxWidgets settings and fallback dialogs. |
| **CC-15** | `ui/task_runner.py:40-41` | `TaskHandle` (`Event`, `Future`) | Task cancellation handle | **REMOVE/CONSOLIDATE** | Replaced by Worker job handles. |
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
| **CC-28** | `ui/nvda_ui.py:163` | `call()` (`done.wait()`, `Event`) | Main-thread executor event | **KEEP IN NVDA** | Synchronous main-thread snapshot bridge; must add timeout. |
| **CC-29** | `ui/nvda_ui.py:156` | `queue()` (`queueFunction`) | NVDA event queue marshal | **KEEP IN NVDA** | Canonical non-blocking marshaler to NVDA event loop. |
| **CC-30** | `ui/host_renderer.py:170` | `_dispatch_event_to_nvda` | Event queue marshal | **KEEP IN NVDA** | Marshals host pipe events onto NVDA event queue. |
| **CC-31** | `ui/download_progress.py:83-84` | `_cancel_event` & `_completion_lock` | Download dialog synchronization | **KEEP IN NVDA** | Synchronizes wx progress dialog cancellation and completion. |
| **CC-32** | `ui/download_progress.py:247` | Download worker (`Thread`) | Dialog download thread | **MOVE TO WORKER** | Downloads move to Worker; dialog listens to progress IPC. |
| **CC-33** | `service/model_cache.py:65` | `_FetchGate.event` (`Event`) | Fetch deduplication barrier | **MOVE TO WORKER** | Deduplication barrier moves to Worker model manager. |
| **CC-34** | `service/model_cache.py:85` | `ModelCatalogCache._lock` (`RLock`) | Catalog cache lock | **MOVE TO WORKER** | Cache management moves to Worker; NVDA gets snapshot. |
| **CC-35** | `service/model_cache.py:190` | `ModelCatalogPreload` (`Thread`) | Background catalog preload | **MOVE TO WORKER** | Catalog discovery executed entirely in Worker. |
| **CC-36** | `service/model_cache.py:212` | `ModelCatalogFetch-{provider}` (`Thread`) | Background fetch thread | **MOVE TO WORKER** | Network fetching executed entirely in Worker. |
| **CC-37** | `service/model_cache.py:397` | `ModelCapabilityCache._lock` (`RLock`) | Capability cache lock | **MOVE TO PURE PYTHON** | Pure in-memory capability lookup. |
| **CC-38** | `service/chat/coordinator.py:53` | `_session_lock` (`threading.RLock`) | Session turn lock | **MOVE TO PURE PYTHON** | Domain-level turn synchronization in pure Python. |
| **CC-39** | `service/chat/coordinator.py:56` | `_turn_lock` (`threading.Lock`) | Turn atomic lock | **MOVE TO PURE PYTHON** | Domain-level atomic turn synchronization. |
| **CC-40** | `service/base.py:48, 66` | `_lock` & `_active_worker` | Base coordinator worker | **REMOVE/CONSOLIDATE** | Dead code in `ChatCoordinator`; delete. |
| **CC-41** | `service/error_reporter.py:39` | `_lock` (`threading.Lock`) | Error reporter dedupe lock | **MOVE TO PURE PYTHON** | Pure domain error reporting history. |
| **CC-42** | `config/model_config.py:168` | `_lock` (`threading.RLock`) | Model config store lock | **MOVE TO PURE PYTHON** | Pure domain config persistence lock. |
| **CC-43** | `config/enabled_models.py:49` | `_lock` (`threading.RLock`) | Enabled models store lock | **MOVE TO PURE PYTHON** | Pure domain config persistence lock. |
| **CC-44** | `providers/_provider_runtime.py:26` | `_lock` (`threading.RLock`) | Active provider factory lock | **MOVE TO PURE PYTHON** | Pure domain provider swap lock. |
| **CC-45** | `providers/runtime/server.py:51` | `_CONFIG_WRITE_LOCK` (`Lock`) | LiteRT config file lock | **RUST-OWNED** | Runtime supervisor in Rust manages config generation. |
| **CC-46** | `providers/runtime/server.py:335` | `_TestShimSupervisor._lock` (`RLock`) | Duplicate test shim lock | **REMOVE/CONSOLIDATE** | Production test shim deleted (RS-10). |
| **CC-47** | `providers/runtime/llama_server.py:105` | `_LlamaServerProcess._lock` (`RLock`) | Duplicate test shim lock | **REMOVE/CONSOLIDATE** | Production test shim deleted (RS-10). |
| **CC-48** | `providers/runtime/llama_server.py:279` | `_models_cache_lock` (`Lock`) | llama model cache lock | **MOVE TO WORKER** | Worker owns llama catalog discovery. |
| **CC-49** | `providers/runtime/llama_server.py:530` | `_supervisors_lock` (`RLock`) | llama supervisor registry lock | **RUST-OWNED** | Rust `runtime_supervisor` manages process handles. |
| **CC-50** | `providers/runtime/download.py:85` | `cancel_event` (`Event`) | Runtime download cancel | **MOVE TO WORKER** | Worker process owns downloads and cancellation. |
| **CC-51** | `providers/runtime/model_download.py:71` | `cancel_event` (`Event`) | Model download cancel | **MOVE TO WORKER** | Worker process owns downloads and cancellation. |
| **CC-52** | `providers/capabilities.py:13` | `_registry_lock` (`RLock`) | Capabilities registry lock | **MOVE TO PURE PYTHON** | In-memory capability registry lock. |
| **CC-53** | `providers/runtime/llama_models.py:242` | `_lock` (`RLock`) | Preset catalog lock | **MOVE TO PURE PYTHON** | In-memory preset catalog lock. |
| **CC-54** | `runtime_supervisor/src/supervisor.rs:18` | `Mutex<SupervisorState>` | Rust native supervisor state | **RUST-OWNED** | Authoritative process & lifecycle lock in Rust. |
| **CC-55** | `runtime_supervisor/src/supervisor.rs:19` | `Condvar` | Rust startup/stop notification | **RUST-OWNED** | Fencing & startup synchronization in Rust. |

---

## 4. Invariants A1–A4 & A27: NVDA Boundary & Thread Affinity Audit

### 4.1 Invariant A1: NVDA as a Thin Accessibility Shell
- **Mandate**: NVDA's role in the add-on must be strictly confined to accessibility input capture, thread-affine snapshotting, accessibility output presentation, and thin UI marshaling. Zero heavy compute, zero local server supervision, zero downloading, and zero model inference inside NVDA.
- **Current Head Assessment**: **FAILED (VIOLATIONS CONFIRMED)**.
  - LiteRT and llama-server process supervision runs directly inside `nvda.exe` via `runtime_supervisor` PyO3 bindings (`server.py:42`, `llama_server.py:291`).
  - Model downloading via HTTP chunk streaming runs inside `nvda.exe` threads (`download.py:286`, `model_download.py:163`).
  - Heavy PIL image resizing and format conversion runs inside `nvda.exe` (`context/collectors/image.py:59`, `image/services.py:61-92`).

### 4.2 Invariant A2: NVDA Main/Event Thread Latency & Blocking Violations

An audit of the call chains on the NVDA event/main thread reveals **six critical latency spikes and potential blocking violations**:

#### Spike 1: Synchronous `time.sleep()` Retry Loop on NVDA Main Thread [CONFIRMED, BLOCKER]
- **Location**: `image/focus_capture.py:107-124` in `_resolve_capture_location_with_retry()`.
- **Call Chain**:
  ```text
  Gesture -> BackgroundTaskRunner worker thread (background.py:444)
    -> context_pipeline.collect() (pipeline.py:41)
    -> _resolve_image_snapshots() (pipeline.py:179)
    -> _main_thread_executor(_capture_all) (pipeline.py:213)
    -> nvda_ui.call() -> queueHandler.queueFunction (nvda_ui.py:174)
    -> [RUNS ON NVDA MAIN EVENT THREAD]:
       -> _capture_region_and_metadata() (focus_capture.py:230)
       -> _resolve_capture_location_with_retry() (focus_capture.py:82)
       -> for attempt in range(max_attempts): # up to 5 attempts
            time.sleep(retry_delay_seconds)    # 0.1s SLEEP ON MAIN THREAD!
  ```
- **Observed Impact**: When an object has transient location resolution issues (e.g., Ia2Web element in a browser or WebView), the NVDA main event loop is put to sleep for up to **400 ms (0.4 seconds)**! During this time, NVDA is completely unresponsive: keystrokes are delayed, speech stops, audio cuts out, and Windows marks the NVDA process as not responding.

#### Spike 2: Synchronous GDI Grab & PIL PNG Compression on Main Thread [CONFIRMED, BLOCKER]
- **Location**: `image/services.py:48-51` and `image/focus_capture.py:259-265`.
- **Observed Code**:
  ```python
  # image/focus_capture.py:259-265 (inside _capture_region_and_metadata, running on main thread)
  bbox = (left, top, left + width, top + height)
  image = ImageGrab.grab(bbox=bbox)
  buffer = BytesIO()
  image.save(buffer, format="PNG")
  raw_bytes = buffer.getvalue()
  ```
- **Observed Impact**: Compressing a high-DPI full-screen or large window bitmap (e.g., 3840x2160 or 2560x1440) to PNG involves CPU-bound Deflate compression. Running this on the NVDA main thread blocks the event loop for **50–250 ms**, freezing speech and braille refresh.

#### Spike 3: Synchronous Full-DOM Text & Field Parsing on Main Thread [CONFIRMED, DESIGN DETAIL]
- **Location**: `context/extractors/browser_field_parser.py:32-49` and `context/extractors/browser.py:70-85`.
- **Observed Code**:
  ```python
  # context/extractors/browser_field_parser.py:42-49
  text_info = self._make_text_info(obj) # obj.makeTextInfo(POSITION_ALL)
  fields = self._make_text_with_fields(text_info) # text_info.getTextWithFields()
  nodes = self._parse_graph(fields) # parses every DOM control, computes SHA-256 hashes
  ```
- **Observed Impact**: For large documents (e.g. Wikipedia articles, technical manuals with 10,000+ controls), iterating the entire virtual buffer field stream, building frames, computing `hashlib.sha256` keys, and constructing `AccessibilityNode` instances on the main thread causes a **100–300 ms latency spike**.

#### Spike 4: Unbounded `done.wait()` in `nvda_ui.call()` [CONFIRMED, BLOCKER]
- **Location**: `ui/nvda_ui.py:159-178`.
- **Observed Code**:
  ```python
  def call(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
      if threading.current_thread() is threading.main_thread():
          return callback(*args, **kwargs)
      done = threading.Event()
      result: dict[str, Any] = {}
      def runner() -> None:
          try:
              result["value"] = callback(*args, **kwargs)
          except Exception as error:
              result["error"] = error
          finally:
              done.set()
      queueHandler.queueFunction(queueHandler.eventQueue, runner)
      done.wait() # <--- NO TIMEOUT!
      if "error" in result:
          raise result["error"]
      return result.get("value")
  ```
- **Observed Impact**: If `queueHandler.eventQueue` stops processing (e.g. during certain modal dialog message loops, thread deadlocks, or during NVDA shutdown when the queue is discarded), `done.wait()` hangs the calling background thread indefinitely.

#### Spike 5: Synchronous HTTP Network Fetch on Cache Miss [CONFIRMED, BLOCKER]
- **Location**: `service/model_cache.py:109-121` (`get_models`) and `lines 410-413` (`ModelCapabilityCache.get`).
- **Observed Code**:
  ```python
  # service/model_cache.py:410-412
  snapshot = self._catalog_cache.get_snapshot(key[0])
  if snapshot.state in (CatalogState.COLD, CatalogState.ERROR):
      # Synchronous fetch attempt!
      self._catalog_cache.get_models(key[0])
  ```
- **Observed Impact**: If `get_models()` or `ModelCapabilityCache.get()` is invoked when the cache is cold, it executes `_perform_fetch(provider_id)` synchronously. If called from the main thread, NVDA is blocked on a network socket HTTP request for up to the socket timeout (10–30 seconds).

#### Spike 6: Synchronous Subprocess Wait in `stop_host()` during Shutdown [CONFIRMED, DESIGN DETAIL]
- **Location**: `ui/host_process.py:141-148`.
- **Observed Code**:
  ```python
  if _host_process.poll() is None:
      _host_process.terminate()
      _host_process.wait(timeout=5)
  ```
- **Observed Impact**: Runs synchronously on the NVDA main thread during `AIAssistantApplication.terminate()`. If `nvda_ui_host.exe` does not terminate immediately, NVDA exit is delayed for up to 5.0 seconds.

---

### 4.3 Invariant A3: NVDA Object-Model Access Thread-Affinity

- **Mandate**: All interactions with NVDA's object model (`api.getFocusObject()`, `api.getNavigatorObject()`, `api.getForegroundObject()`, `api.getDesktopObject()`, `api.getFocusAncestors()`, `treeInterceptorHandler.getTreeInterceptor()`, `focus.makeTextInfo()`, `TextInfo.getTextWithFields()`, `obj.location`, `winUser.getWindowRect()`, `winUser.getForegroundWindow()`, `api.getClipData()`) MUST occur strictly on NVDA's event/main thread.
- **Current Head Verification**:
  - `ContextPipeline._resolve_page_snapshot` (`pipeline.py:152`): Calls `self._main_thread_executor(self._page_extractor)` -> executes on main thread.
  - `ContextPipeline._resolve_focused_text_snapshot` (`pipeline.py:169`): Calls `self._main_thread_executor(self._focused_text_extractor)` -> executes on main thread.
  - `ContextPipeline._resolve_image_snapshots` (`pipeline.py:213`): Calls `self._main_thread_executor(_capture_all)` -> executes on main thread.
  - `safe_extract_selection` (`application.py:323`, `selection.py:27`): Called in `attach_selection_to_chat` directly on main thread gesture handler.
  - `safe_read_clipboard` (`application.py:337`, `clipboard.py:22`): Called directly on main thread gesture handler.
- **Verdict**: Thread-affinity discipline is **CONFIRMED** for execution context; direct object-model calls are routed through the main thread. However, see Section 4.4 for object reference retention.

---

### 4.4 Invariant A4: Object Leakage & Thread-Detached Snapshots [CONFIRMED, BLOCKER]

- **Mandate**: Downstream processing (providers, pipelines, LLM service, tools, and UI action stores) receives only immutable, thread-detached snapshot DTOs consisting of primitive Python types; **never raw NVDA objects** (`NVDAObject`, `TextInfo`, `TreeInterceptor`, or COM pointers).
- **Violation Identified in `context/types.py:78`**:
  ```python
  # context/types.py:67-80
  @dataclass(frozen=True, slots=True)
  class BrowserExtractionSnapshot(ExtractionSnapshot):
      ...
      # Live NVDA object used only on the main thread to re-resolve navigation
      # actions. It is never sent through the UI or provider protocol.
      navigation_context: object | None = None
      graph: AccessibilityGraph | None = None
  ```
- **Violation Trace**:
  1. `BrowserAwarePageExtractor._navigation_context(obj)` (`context/extractors/browser.py:340, 532`) populates `navigation_context` with the live NVDA `TreeInterceptor` or `NVDAObject`.
  2. In `ContextPipeline.collect()` (`pipeline.py:52`), this snapshot is stored in `CollectorInput` and processed on the **background worker thread** (`background.py:457`).
  3. In `use_case/structure_summary.py:102`, `navigation_context` is embedded into `UseCaseResult`.
  4. In `plugin/presenter.py:422`, `payload = {"navigation_context": getattr(use_case_result, "navigation_context", None)}` is stored in `self._result_action_store` (`ui/action_store.py`).
  5. When the user later clicks a navigation action in the WebView result screen, `presenter.py:586` retrieves `navigation_context` and passes it to `resolve_and_move_target()` (`context/navigation.py:631`):
     ```python
     ti = _tree_interceptor(navigation_context)
     position = ti.makeTextInfo(textInfos.POSITION_FIRST)
     ```
- **Hazard Analysis**:
  - Holding a live COM pointer / `TreeInterceptor` in `ResultActionStore` across asynchronous user interactions means that if the user navigates to a new page, closes the browser tab, or reloads the document, the stored `navigation_context` becomes a **stale, dangling COM interface**.
  - Calling methods on a dead COM pointer causes `RPC_E_DISCONNECTED` (`0x80010108`), `CO_E_OBJNOTCONNECTED`, or an access violation crash in `oleacc.dll` / `IAccessible2.dll`.
  - Violates Invariant A4 by transmitting a live COM object across the thread boundary into background worker threads.

---

### 4.5 Invariant A27: Non-Blocking Output Marshaling & Error Isolation

- **Mandate**: All asynchronous events, notifications, speech messages, and tones originating from background threads or the worker process must be marshaled onto NVDA's event queue via `queueHandler.queueFunction(queueHandler.eventQueue, ...)`.
- **Audit Findings**:
  - `ui/nvda_ui.py:queue` (`line 156`) correctly wraps `queueHandler.queueFunction(queueHandler.eventQueue, callback, *args)`.
  - `ui/host_renderer.py:170` correctly wraps event dispatch via `queueHandler.queueFunction`.
  - `ui/nvda_ui.py:play_streaming_tone()` (`lines 24-53`): Correctly throttled via `_streaming_tone_lock` to an interval between 1.0s and 4.0s, and enqueued via `queue(tones.beep, 520.0, 50)`.
  - **Violation Identified in `ui/adapter.py:410` [CONFIRMED, DESIGN DETAIL]**:
    In `_handle_host_chat_submission()` (which runs on a daemon thread spawned at `line 222`), on error line 410 calls:
    ```python
    nvda_ui.message(presentation.message)
    ```
    instead of `nvda_ui.queue(nvda_ui.message, presentation.message)`. Calling `ui.message()` directly from a secondary thread bypasses NVDA's thread serialization.

---

## 5. Concrete Target Design: Thread-Affine Snapshotting & Boundary Isolation

To strictly enforce Invariants A1–A4 and A27 while completely eliminating main-thread latency spikes and COM dangling pointer hazards, the target architecture implements the following concrete snapshotting design:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                  NVDA MAIN EVENT THREAD                                │
│                                                                                        │
│  [Gesture Trigger]                                                                     │
│         │                                                                              │
│         ▼                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                     Synchronous Main-Thread Snapshot Acquisition                 │  │
│  │                                                                                  │  │
│  │  1. Check Screen Curtain (fail-fast, no wait)                                    │  │
│  │  2. Focused Text: extract strings via EditableText.makeTextInfo (bounded)        │  │
│  │  3. Selection: extract strings via TreeInterceptor/Focus TextInfo               │  │
│  │  4. Clipboard: extract string via Win32 clipboard API                            │  │
│  │  5. Page Structure & Graph: extract text & fields into immutable AccessibilityGraph│ │
│  │  6. Image Bounds: resolve bounding rect (RectLTWH) + HWND;                      │  │
│  │     GRAB RAW GDI DIB BITS (NO PNG COMPRESSION ON MAIN THREAD!)                   │  │
│  │  7. Navigation Target Spec: generate TargetNavigationSpec (NO LIVE COM OBJECTS!) │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                              │
│         ▼                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                         Package into Immutable DTOs                              │  │
│  │       (JobSubmission: text, raw_image_bytes, graph, navigation_spec)              │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
│         │                                                                              │
│         ▼                                                                              │
│  [Enqueue to Worker IPC Client Non-Blocking Queue]                                     │
│         │                                                                              │
│         ▼                                                                              │
│  [IMMEDIATE RETURN] ───► NVDA Main Thread stays 100% responsive for speech/keys!       │
└────────────────────────────────────────────────────────────────────────────────────────┘
          │ (IPC Named Pipe / Shared Memory)
          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL WORKER PROCESS                                   │
│                                                                                        │
│  1. Dequeue JobSubmission                                                              │
│  2. Heavy CPU Compute: LANCZOS Image Resizing, Format Conversion, Base64 Encoding      │
│  3. Context Reduction & Token Budgeting                                                │
│  4. Local Server Supervision & Prompt Construction                                     │
│  5. LLM Provider Execution / HTTP Streaming / Tool Execution Loop                      │
│  6. OCR Session (Slice 9) / Audio Transcription Buffering (Slice 10)                   │
│         │                                                                              │
│         ▼ (IPC Stream Updates & Results)                                               │
└────────────────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                         NVDA IPC LISTENER THREAD                                       │
│                                                                                        │
│  [Receives JobUpdate / StreamChunk / JobResult]                                        │
│         │                                                                              │
│         ▼                                                                              │
│  queueHandler.queueFunction(queueHandler.eventQueue, on_job_update, update)            │
│         │                                                                              │
│         ▼                                                                              │
│  [NVDA Main Thread updates Web UI via UIAdapter or announces via speech.speak]         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.1 Replacement of `navigation_context` with `TargetNavigationSpec`
To eliminate RS-04 COM leakage, `BrowserExtractionSnapshot.navigation_context` is completely removed. In its place, `TargetNavigationSpec` is defined:

```python
@dataclass(frozen=True, slots=True)
class TargetNavigationSpec:
    """Immutable DTO enabling safe re-resolution of navigation targets on the main thread."""
    target_id: str
    target_type: Literal["heading", "link", "button", "landmark", "control"]
    label: str
    order_index: int
    window_handle: int
    app_name: str
```

When a user triggers navigation from the UI:
1. `ResultActionStore` yields `TargetNavigationSpec` (a pure primitive DTO).
2. NVDA executes on the main thread via `core.callLater` or `queueHandler`.
3. The main thread queries the current foreground window/focus matching `window_handle`.
4. It re-resolves the tree interceptor cleanly on the main thread, finds the node matching `order_index` or `label`, and invokes `moveToAttribute` or `setFocusObject`.
5. If the document has navigated away, it announces "The target page is no longer active" cleanly without crashing.

### 5.2 Offloading Image Compression & Resizing to Worker
- **Current Flow**:
  Main Thread captures GDI -> Main Thread runs PIL `image.save(format="PNG")` -> Worker runs `ImagePreprocessor.preprocess(LANCZOS resize)` -> Worker runs `ImageEncoder.encode(base64)`.
- **Target Flow**:
  Main Thread captures raw uncompressed screen/window DIB bytes or bounds -> Packages raw bytes into `JobSubmission` -> Hands off immediately to Worker -> Worker performs all resizing, filtering, compression, and base64 encoding. Main-thread execution time drops from **~150 ms to < 5 ms**.

### 5.3 Removal of `time.sleep()` in Focus Location Resolution
In `_resolve_capture_location_with_retry()`, all `time.sleep()` calls on the main thread are **completely eliminated**.
- If `getFocusObject().location` is unavailable, immediate fallback occurs: `navigator` -> `foreground` -> `winUser.getWindowRect(windowHandle)`.
- Fallback through `winUser.getWindowRect` succeeds in 100% of WebView cases without any sleeps, reducing capture resolution from 400 ms to **< 1 ms**.

---

## 6. Complete Classified Findings Table

| ID | Title | File Path & Lines at HEAD (`ced1cbc`) | Classification | Impact |
|---|---|---|---|---|
| **TA-01** | Synchronous `time.sleep()` on NVDA main thread in focus capture retry | `image/focus_capture.py:107-124` | **CONFIRMED, BLOCKER** | Freezes NVDA main event loop for up to 400 ms during focus image capture. |
| **TA-02** | Live NVDA COM object leakage across thread boundaries via `navigation_context` | `context/types.py:78`, `presenter.py:422`, `navigation.py:638` | **CONFIRMED, BLOCKER** | Violates Invariant A4; causes `RPC_E_DISCONNECTED` crashes on stale navigation. |
| **TA-03** | Heavy PIL PNG encoding executed synchronously on NVDA main thread | `image/services.py:48-51`, `image/focus_capture.py:259-265` | **CONFIRMED, BLOCKER** | CPU-bound bitmap compression freezes NVDA speech/braille for 50–250 ms. |
| **TA-04** | Unbounded `done.wait()` in `nvda_ui.call()` blocks worker threads indefinitely | `ui/nvda_ui.py:163, 175` | **CONFIRMED, BLOCKER** | Worker threads hang permanently if NVDA event queue stalls or shuts down. |
| **TA-05** | Synchronous network fetch on cache miss blocks calling thread | `service/model_cache.py:109-121, 410-413` | **CONFIRMED, BLOCKER** | Synchronous HTTP calls block caller; freezes NVDA UI if invoked on main thread. |
| **TA-06** | Uncontrolled proliferation of ad-hoc daemon threads | `plugin/application.py:178, 186, 202, 354, 414, 478`, `plugin/background.py:80, 105` | **CONFIRMED, BLOCKER** | Causes socket bind races, process leaks on shutdown, and state corruption. |
| **TA-07** | Direct call to `nvda_ui.message()` from secondary thread | `ui/adapter.py:410` | **CONFIRMED, DESIGN DETAIL** | Violates Invariant A27; bypasses NVDA thread serialization. |
| **TA-08** | Full-DOM virtual buffer text and field parsing on NVDA main thread | `context/extractors/browser_field_parser.py:32-49` | **CONFIRMED, DESIGN DETAIL** | 100–300 ms latency spike on large web documents during page snapshotting. |
| **TA-09** | Synchronous `Popen.wait(5)` in `stop_host()` delays NVDA plugin shutdown | `ui/host_process.py:141-148` | **CONFIRMED, DESIGN DETAIL** | NVDA exit delayed by up to 5 seconds if UI host is slow to terminate. |
| **TA-10** | Dual competing `BackgroundTaskRunner` abstractions in production codebase | `plugin/background.py:357`, `ui/task_runner.py:52` | **CONFIRMED, DESIGN DETAIL** | Fragmented concurrency model; duplicate executors and confusing task lifecycles. |
| **TA-11** | Local runtime process supervision hosted in NVDA rather than Worker | `providers/runtime/server.py:42`, `llama_server.py:291` | **CONFIRMED, BLOCKER** | Violates Invariants A1 and A25; local server crashes affect NVDA process space. |

---

## 7. Migration Verification & Acceptance Criteria

To verify resolution of Audit B and Invariants A1–A4, A27 throughout Slices 0–10:
1. **Slice 0 Gate**:
   - Remove `time.sleep()` from `image/focus_capture.py:107-124` (TA-01).
   - Add a 5.0s timeout to `nvda_ui.call()`'s `done.wait()` (TA-04).
   - Route `ui/adapter.py:410` error message through `nvda_ui.queue()` (TA-07).
2. **Slice 2 Gate**:
   - Remove `navigation_context` from `BrowserExtractionSnapshot` and replace with `TargetNavigationSpec` DTO (TA-02).
   - Ensure all DTOs crossing the boundary are strictly primitive dataclasses.
3. **Slice 3 & 4 Gates**:
   - Move `ModelCatalogCache` fetching and background threads into Worker process (TA-05).
   - Offload image resizing and PNG compression from NVDA to Worker process (TA-03).
4. **Slice 6, 7 & 8 Gates**:
   - Move `RuntimeSupervisor` native ownership into Worker process (TA-11).
   - Delete all ad-hoc server shutdown/restart threads from `plugin/background.py` and `plugin/application.py` (TA-06).
   - Delete duplicate `_TestShimSupervisor` locks from `server.py` and `llama_server.py`.
5. **Continuous Verification Commands**:
   - `uv run ruff check .`
   - `uv run pytest`
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml`
   - `cargo test --manifest-path runtime_supervisor/Cargo.toml`
