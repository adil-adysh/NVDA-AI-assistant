# Python development and tests

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
controller visibility, and foreground restoration. It starts no IPC listeners.

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
