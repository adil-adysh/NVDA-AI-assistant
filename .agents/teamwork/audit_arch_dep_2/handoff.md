# Handoff Report: Audits A, C, and G

**Author**: Current Architecture & Dependency Auditor (Agent 1)  
**Date**: 2026-10-02  
**Commit HEAD**: `ced1cbc`  
**Working Directory**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_arch_dep_2`  
**Recipient**: Parent Orchestrator (`9e3c7398-1a1a-4933-bc73-5d9f0a8d166f`)  
**Deliverable**: `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_arch_dep_2\audit_report.md`  

---

## 1. Observation

1. **Process Topology & Subprocess Management**:
   - `nvda_ui_host.exe` is launched via `subprocess.Popen` in `addon/globalPlugins/AI-assistant/ui/host_process.py:86` with `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`, `stdout=subprocess.PIPE`.
   - LiteRT and llama server shutdowns in `addon/globalPlugins/AI-assistant/plugin/application.py:178–192` run as fire-and-forget daemon threads:
     ```python
     threading.Thread(target=get_litert_supervisor().stop, name="LiteRTServerShutdown", daemon=True).start()
     threading.Thread(target=shutdown_llama_servers, name="LlamaServerShutdown", daemon=True).start()
     ```
   - LiteRT CLI operations (`import`, `list`, `dir`, `remove`) in `providers/runtime/server.py:299` run synchronously via `subprocess.run` inside NVDA Python threads with deadlines up to 120 seconds (`server.py:870`).
   - Four PyO3 extensions (`runtime_supervisor.pyd`, `llm_client.pyd`, `memory_engine.pyd`, `embedding_engine.pyd`) in `addon/globalPlugins/AI-assistant/lib/` run directly in-process within `nvda.exe`.

2. **NVDA Import Contamination**:
   - AST analysis of all 114 Python files identified 95 NVDA imports across the add-on.
   - 40 out of 95 imports (42.1%) are `from logHandler import log` (e.g. `service/base.py:8`, `service/chat/coordinator.py:9`, `providers/runtime/download.py:27`, `config/state.py:7`).
   - `config/settings.py:8` imports `import languageHandler`, used solely in `get_effective_language()` at line 200:
     ```python
     language_value = languageHandler.getLanguage() or "en"
     ```
   - `core/`, `tools/`, `use_case/`, and `embeddings/` contain exactly **0 NVDA imports**.
   - `utils/clipboard.py:21` imports `import api` to call `api.getClipData()`, contradicting its pure-Python docstring.

3. **`plugin/background.py` Decomposition**:
   - Total file length: 495 lines.
   - `BackgroundTaskRunner._start_worker` (`background.py:384–402`) spawns raw `threading.Thread(daemon=True)` instances without bounding, queueing, or cancellation handles.
   - `ensure_provider_server_ready` (`background.py:184–196`) silently mutates application configuration via `set_model_name(record.model_id)` during model fallback.
   - Background worker threads directly invoke NVDA main-thread speech output via `nvda_ui.queue(nvda_ui.message, _(...))` at lines 416, 422, 434, 451.

4. **Baseline Verification Commands**:
   - `uv run ruff check .` passed with code 0 (All checks passed).
   - `cargo check --manifest-path nvda_ui_host/Cargo.toml` passed with code 0 (0.04s).
   - `uv run cargo test --manifest-path runtime_supervisor/Cargo.toml` passed with code 0 (11 passed, 1.54s).
   - `uv run pytest` passed with code 0 (461 passed, 3 deselected, 13.99s).

---

## 2. Logic Chain

1. **Step 1 (Process Isolation Risk)**: From Observation 1, native PyO3 extensions (`embedding_engine`, `memory_engine`, `llm_client`) run inside `nvda.exe`, and daemon threads manage server termination upon NVDA exit. If native code panics or runs out of memory, `nvda.exe` crashes immediately. If NVDA terminates while daemon shutdown threads are running, child servers are orphaned. Therefore, moving compute and server supervision to an out-of-process Worker Process (Invariants A1, A16–A18) is strictly necessary for screen reader stability.
2. **Step 2 (Pure-Python Boundary Feasibility)**: From Observation 2, `core`, `tools`, `use_case`, and `embeddings` are already pure Python (0 NVDA imports), and `service`, `providers`, `prompts`, `observability`, and `config` are contaminated almost exclusively by `from logHandler import log` (40 instances) plus one `languageHandler` import. Because `logHandler` can be drop-in replaced by Python's standard `logging.getLogger(__name__)`, over 80% of the codebase can immediately operate as a standalone pure-Python domain/service tree (enforcing Invariants A5–A6, A30).
3. **Step 3 (`plugin/background.py` Deconstructability)**: From Observation 3, `plugin/background.py` is conflating 5 orthogonal concerns: local server readiness, CLI model import, hardware detection, thread management, and speech presentation. Every function and class maps directly to a clean destination module (`providers/runtime/supervisor_service.py`, `service/provider_readiness.py`, `service/model_management/`, `plugin/presenter.py`, and `service/job_executor.py`).

---

## 3. Caveats

1. **NVDA Live Integration Tests**: As noted in Audit D, `uv run pytest -m nvda_integration` fails on machines where COM typelib timestamps differ from generated comtypes caches. The default test suite (`uv run pytest`) passes 100% of 461 tests cleanly.
2. **PyO3 Python Version**: `cargo test` must be invoked via `uv run cargo test` or with `PYO3_PYTHON` pointing to the Python 3.13 virtual environment when a newer system Python (e.g. 3.14) is on PATH.
3. **No Code Written to Production**: This audit is strictly read-only. No changes were made to production source files.

---

## 4. Conclusion

Audits A, C, and G are complete with code citations from HEAD (`ced1cbc`).
- **Audit A**: Complete mapping of the 6 running process categories, boundary crossings, failure propagation, and contrast with target worker topology.
- **Audit C**: Complete inventory of all 95 NVDA imports; definition of the maximum coherent pure-Python domain subtree (92 of 114 files); and automated Ruff banned-API and AST lint rules.
- **Audit G**: Line-by-line deconstruction of `plugin/background.py` (lines 1–495) with concrete target destination modules for all symbols.
- All findings are classified with mandatory tags (`CONFIRMED`, `LIKELY`, `DESIGN DETAIL`, `BLOCKER`).
- Complete report is saved at `D:\nvda-addons\NVDA-AI-assistant\.agents\teamwork\audit_arch_dep_2\audit_report.md`.

---

## 5. Verification Method

To independently verify all findings and baseline claims:

1. **Verify Baseline Quality**:
   ```pwsh
   uv run ruff check .
   uv run pytest
   cargo check --manifest-path nvda_ui_host/Cargo.toml
   uv run cargo test --manifest-path runtime_supervisor/Cargo.toml
   ```
2. **Verify AST Import Counts (Audit C)**:
   ```pwsh
   uv run python -c "import ast, pathlib; modules = {'api','textInfos','controlTypes','globalPluginHandler','scriptHandler','queueHandler','gui','guiHelper','wx','speech','tones','logHandler','languageHandler','addonHandler','treeInterceptorHandler','cursorManager','braille','winUser','locationHelper'}; p = pathlib.Path('addon/globalPlugins/AI-assistant'); count = sum(1 for f in p.rglob('*.py') if 'lib' not in f.parts for n in ast.walk(ast.parse(f.read_text(encoding='utf-8', errors='replace'))) if (isinstance(n, ast.Import) and any(a.name.split('.')[0] in modules for a in n.names)) or (isinstance(n, ast.ImportFrom) and n.module and n.module.split('.')[0] in modules)); print(f'Total NVDA imports: {count}')"
   ```
   *Expected output*: `Total NVDA imports: 95`.
3. **Verify Line Numbers in `plugin/background.py` (Audit G)**:
   - Line 10: `from logHandler import log`
   - Lines 42–44: `_NON_LLM_USE_CASES`
   - Lines 51, 80: `_on_litert_server_config_changed`, thread spawn
   - Line 112: `subscribe_llama_server_config_change`
   - Line 163: `ensure_provider_server_ready`
   - Line 194: `set_model_name(record.model_id)`
   - Line 212: `_ensure_model_imported`
   - Line 357: `class BackgroundTaskRunner`
   - Lines 384–402: `_start_worker` raw thread creation
   - Lines 416, 422, 434, 451, 491: `nvda_ui.queue` dispatches
