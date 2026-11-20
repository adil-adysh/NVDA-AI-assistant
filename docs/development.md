# Python development and tests

After building `runtime_supervisor` with the locked `PYO3_PYTHON`, run
`uv run python tests/worker/native_shutdown_smoke.py` on Windows. This loads the
debug DLL directly and exercises both real worker executors: owned child exit,
rejected launches through borrowed native references, and preservation of
externally adopted HTTP servers. It uses disposable local HTTP servers and does
not start an inference model or restart NVDA.

Python development uses [uv](https://docs.astral.sh/uv/) and Python 3.13.12,
matching the sibling NVDA source checkout. Clone NVDA beside this repository:

~~~powershell
cd ..
git clone https://github.com/nvaccess/nvda.git nvda
git -C nvda checkout 797a881381f8bedabc13456d3aa76bdd77d71503
cd NVDA-AI-assistant
uv sync --locked
~~~

The pytest bootstrap resolves `../nvda` relative to this repository and adds
NVDA's `source` and `miscDeps/python` directories itself. No `PYTHONPATH` or
machine-specific path is required. A missing checkout produces an actionable
pytest startup error instead of installing or creating a fake NVDA package.
The tested NVDA commit is recorded in `nvda-source.toml`; local runs warn on a
different revision and CI rejects it.

Run the suite and lint checks with:

~~~powershell
uv run pytest
uv run ruff check .
~~~

The default suite uses importable NVDA API definitions but does not require
NVDA's native build outputs. To prepare and build the optional runtime tier:

~~~powershell
git -C ../nvda submodule update --init --recursive
cd ../nvda
uv sync
uv run scons
cd ../NVDA-AI-assistant
~~~

The integration bootstrap also discovers the sibling checkout's `.venv` for
NVDA's locked runtime-only dependencies. Then run the runtime-bound tier
explicitly:

~~~powershell
uv run pytest -m nvda_integration
~~~

Run one file or one test by passing its pytest node ID:

~~~powershell
uv run pytest tests/integration/test_nvda_imports.py
uv run pytest tests/integration/test_nvda_imports.py::test_nvda_api_definitions_come_from_sibling_checkout
~~~

Cross-component integration tests live under `tests/integration/`. Controlled
providers use `threading.Event` barriers so tests decide exactly when a request
streams, completes, or fails. Race tests should assert the intended ordering at
the provider, session, persistence, and presentation boundaries and must not use
arbitrary sleeps. The fakes implement the provider contract and never contact a
paid or external model API.

Managed llama.cpp and LiteRT-LM process/cache behavior is specified in
`docs/local-provider-lifecycle.md`. Its integration tests keep the real
supervisor locking, startup fingerprinting, invalidation, and cleanup code in
the loop while replacing only the heavyweight OS process and health boundary.

The standalone suite imports real NVDA API definitions. Live process state
(focus objects, the event loop, GUI objects, speech, and native helper DLLs)
is still replaced at narrow test boundaries when a running, built NVDA process
would otherwise be required. The normal add-on package build remains `scons`.
The bundle writer rejects test directories, test modules, pytest configuration,
and bytecode unconditionally, so none of these files can enter an
`.nvda-addon` archive.

## Private worker bundle

Web UI action, shortcut, and conversation regression tests run with
`npm --prefix nvda_ui_host run test:webui` after installing the locked Web UI
dependencies. They execute production TypeScript and replace only browser,
host-transport, and reactive-state boundaries. The real wx settings controls
are covered by the normal Python suite.

`uv run scons` builds the native extensions, then bundles the official CPython
3.13.12 Windows amd64 embeddable runtime and locked pywin32 dependencies in
`worker_host/`. The builder verifies the pinned download checksum, replaces
the official bytecode standard-library zip with matching source, and validates
bundle checksums and exclusions. No system Python or pip is needed on the user
machine. `uv run python scripts/build_worker_bundle.py` rebuilds just this bundle
after the native extension is installed. `scripts/build.py --install-only`
requires a complete, validated existing bundle.

The native build action selects the locked uv project environment even when
SCons was launched from a global Python installation. Direct
`python scripts/build.py` also delegates to that environment. Python and
pywin32 versions are checked before compilation; keep uv installed and run
`uv sync --locked` to prepare or update the build environment.

For direct Rust supervisor tests on Windows, select the same interpreter:

~~~powershell
$env:PYO3_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
cargo test --manifest-path runtime_supervisor/Cargo.toml
~~~

Without this selection, PyO3 may discover an unsupported system Python.

Edit the tracked root `readme.md` for English user documentation. SCons copies
it into `addon/doc/en/readme.md` and generates HTML; those copies are build output.

`uv run pytest tests/build/test_worker_bundle_smoke.py` copies the bundle and
worker/core source into an isolated temporary directory, clears external Python
paths, and exercises a real handshake, native status, and download job. Build
the bundle first; this test skips when its executable is absent.

For release validation, set `NVDA_AI_REQUIRE_PACKAGED_TESTS=1` before running
the packaged smoke tests. Missing build artifacts then fail instead of skipping.
The add-on build/release workflow runs this gate after building the package,
together with the real Windows parent-process and LiteRT path-contract tests.
The smoke test verifies health across multiple parent-watchdog ticks, rather
than stopping immediately after a successful handshake.

Keep filesystem resolution and platform APIs real in boundary tests. LiteRT
path tests compare the worker defaults with the installer resolver and pass
adapter commands through the real worker handler and executor, replacing only
the final native process launch. Unit tests that mock paths or native process
creation cannot establish that the packaged application will locate an installed
runtime. Live NVDA gesture, focus, speech, cancellation, and install/update checks
remain a separate release validation step.

For native dismissal/focus changes, run the interactive WebView2 regression
on a Windows desktop with WebView2 installed:

~~~powershell
cargo test --manifest-path nvda_ui_host/Cargo.toml --lib real_one_shot_close_and_escape_hide_webview_and_reopen -- --ignored
~~~

It renders a real one-shot result, clicks its Close button, reopens for another
result, and invokes native Escape. Assertions check the outer HWND, embedded
controller visibility, and foreground restoration. Its chat scenario sends a
128-delta burst followed by completion and checks that the composer draft and
caret stay intact. It starts no IPC listeners.

Application composition registers `configure_worker_owner()` without spawning.
Runtime settings offer three startup policies for each managed local provider:
start when needed (the default), prepare the background worker at startup, or
start the local server at startup. Only the active provider's policy is applied,
on the next NVDA startup. Older saved server-start booleans map to the equivalent
policy; saving updates both the policy and the legacy flag.
Model mutations, downloads, and inference explicitly request a worker; status
lookups remain passive. Worker preparation uses the same owned lazy connection;
it neither checks for an installed model server nor starts one. Other future
application startup integrations can use
`configure_worker_owner(start_on_startup=True)` or the owner's
`start_in_background()` without starting a model server. Local-server
startup settings invoke the normal readiness path on a background thread.
Shutdown permanently fences launches and automatic restarts before background
process teardown.

### LiteRT runtime package upgrades

Installing LiteRT-LM also finalizes cached installations. Finalization verifies
manifest identity and every declared SHA-256 before retiring the recognized
0.15.0 package. The worker checks native supervisor status; cleanup is deferred
while a server is running or adopted, or when Windows holds package files open.
Repeat installation retries deferred cleanup. Failed verification or cancelled
installation retains the previous package. The separate model registry is never
part of runtime retirement. `core/runtime_upgrade.py` owns package verification
and retirement policy; the worker retains authority over process status.

### Worker isolation checks

`tests/worker/test_runtime_jobs.py` verifies cancellation, stale generations,
terminal-event retention, blocked pipe writes, independent execution lanes, Stop
with busy ordinary execution capacity, late startup cancellation and passive
status reads. Run packaged smoke tests with `NVDA_AI_REQUIRE_PACKAGED_TESTS=1`
after `uv run scons`; the suite then fails instead of skipping missing artifacts.
Do not run the package build concurrently with tests that load bundled DLLs.

The explicit `uv run pytest -m nvda_integration` command isolates collection to
files declaring that marker; normal marker deselection happens too late to
prevent standalone GUI stubs from affecting real NVDA imports. If COM imports
report `Typelib different than module`, regenerate the sibling checkout's
`source/comInterfaces` target with its supported `scons.bat` build workflow.


### llama.cpp model management compatibility checks

Run `uv run pytest tests/core/test_hf_cache.py tests/providers/test_deterministic_llama_management.py tests/providers/test_llama_configuration_transactions.py tests/providers/runtime/test_llama_models.py tests/providers/test_llama_provider.py tests/ui/test_llama_preset_sources.py`.

The cache inventory tests build a temporary cache with `refs/main`, role-specific
GGUF headers, an older snapshot, a malformed file, a broken link and split
groups. They do not read the real user cache. The real router smoke requires an
installed `llama-server`; set `NVDA_AI_REQUIRE_LLAMA_TESTS=1` to fail instead of
skipping when absent. It verifies router discovery of a generated version-1
preset with startup model loading disabled and offline mode enabled; it neither
downloads weights nor performs inference.

The editor and picker are checked manually because wx dialogs need a running NVDA
process. The source picker lists only readable GGUFs from the `refs/main` snapshot,
shows the observed commit as advisory, and returns repository plus exact filename.
No local path is persisted.

### llama.cpp real-world UX acceptance

The advanced manager has one preset list. Add/Edit exposes two source modes for
the main model and the optional draft model: a pass-through manual Hugging Face
reference, or a cached repository plus exact file. The projector is automatic
same-repository or disabled; cached projectors are informational.

Before release, manually exercise with running NVDA:

- Add a manual reference with and without `:quant`; confirm it is stored unchanged.
- Add a cached main model and cached draft; confirm only repository + filename are stored.
- Switch source modes and confirm hidden values are not serialized.
- Enable a draft, disable it, and confirm an automatically added speculative mode is removed.
- Confirm an incomplete split is not selectable and a malformed GGUF is absent.
- Confirm the commit is labelled advisory and the preset still follows `main`.
- Confirm the projector list is informational and cross-repository selection is unavailable.
- Add/Edit/Duplicate/Remove, Preview, Problems navigation, Escape and focus return.
- Empty cache, cache scan failure, no matching role and malformed-GGUF states.
- Manual reference with and without `:quant`; cached main model; cached draft.
- Mode switching preserves hidden values but serializes only the active mode.
- Problems list focus and Go to problem; Preview copy; Cancel leaves state untouched.
- Remove remains explicit and cached model files are kept.
- Friendly names/exact IDs agree in manager, settings, host and gesture menus;
  unavailable current presets remain identifiable and manageable.

Do not interpret automated hidden-dialog tests as live speech/focus acceptance.
