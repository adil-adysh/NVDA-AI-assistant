# Packaged worker and lazy local-server startup

## Intent and agreed direction

Repair local model operations in an installed NVDA add-on without requiring
system Python. The user selected a packaged standalone worker with lazy server
startup. Opening chat and settings must remain responsive, and NVDA object
access must stay on the NVDA event thread.

The current application creates neither a worker supervisor nor a native runtime
supervisor. Provider supervisors accept injected native supervisors for tests,
but their default production path requires a worker that is never started.
The source worker launcher also uses `sys.executable`, which is NVDA's executable
inside NVDA, and the build does not package a worker executable.

## Process and startup contract

1. Package a private Windows CPython runtime under
   `addon/globalPlugins/AI-assistant/worker_host/`. Use the official CPython
   3.13 embeddable distribution, matching the locked development interpreter,
   with a version and checksum pinned by the builder. Launch its `python.exe`
   with `-B -m worker` and the packaged `worker/__main__.py`, with no console window.
   Do not use PyInstaller. Vendor only required dependencies from the locked
   development environment, including named-pipe support and the native
   `runtime_supervisor` extension. No system Python or end-user pip is needed.
   Do not bundle NVDA, GUI libraries, tests, pytest configuration, fixtures,
   or Python bytecode, including bytecode inside nested archives.
2. Application composition registers a lazy worker owner without launching it.
   The first background model operation requests a connected worker. Concurrent
   requests share one startup and handshake. A non-starting lookup is retained
   for status reads and settings initialization.
3. A worker handshake does not start a model server. Existing readiness paths
   start the selected server on the first inference request. Download, import,
   and model management operations may start the worker without starting a
   server unless the underlying operation explicitly needs it.
4. Preserve existing LiteRT and llama startup-preload settings and stored values.
   New configurations default both settings to false, matching lazy startup.
   When enabled,
   they schedule the same readiness path on a background thread. Opening chat
   without sending a prompt does not force server readiness.
   Provide an independent worker prelaunch hook on the same application owner
   so a future startup setting can connect the worker without starting a server.
5. Rust `runtime_supervisor` remains the authoritative child-server lifecycle
   owner, now inside the packaged worker. Python selects configuration and
   model identity. Providers keep their existing worker command interfaces.

## Launch and connection ownership

Prefer the packaged private interpreter and worker script. Source development may use a real Python
interpreter plus the repository entry point. Never interpret NVDA's executable
as Python or fall back to a program found through the current directory.

Use per-owner pipe names to avoid connecting to a different NVDA instance.
Retain the existing handshake version, command/event separation, stderr ring
buffer, Job Object containment, restart circuit breaker, and generation token.
Missing artifacts and failed handshakes produce actionable errors instead of
silently reverting to another runtime ownership path.

The application owns supervisor shutdown. Shutdown rejects further lazy startup,
cancels pending startup, stops the worker and contained server processes, and
clears the registered owner. Slow IPC teardown runs off the NVDA event thread;
containment remains the final cleanup mechanism.

## Build and package contract

Add the worker build to `scripts/build.py` after native extensions are installed.
Add worker source, entry point, bundle builder, and locked dependencies to
SCons inputs. Configure an explicit `python313._pth` so the interpreter uses
only bundled standard-library, dependency, and add-on worker/core paths;
do not enable site initialization or inherit NVDA's Python environment.
The official embeddable standard-library archive contains bytecode. Replace it
with a source-only standard-library archive from the matching locked interpreter,
excluding tests, fixtures, site-packages, and bytecode. Keep required binary
standard-library extensions and license notices. Validate the resulting archive
contents recursively. Build-time dependency setup remains `uv sync --locked`.
The normal `uv run scons` package includes the complete worker directory,
with no dependency on source checkout
paths. `--install-only` may reuse an existing complete worker bundle and must
fail clearly if it is missing.

Preserve `site_scons/site_tools/NVDATool/addon.py` exclusions. Keep downloaded
archives and build scratch output outside `addon/`. Inspect the resulting `.nvda-addon` for forbidden
files and perform a standalone handshake from an extracted bundle with an
unrelated working directory.

## Failure behavior

Worker startup failures affect model operations, not NVDA initialization or
non-inference chat opening. Concurrent callers receive the same startup outcome.
Termination cannot launch a replacement worker. A restarted worker advertises
the supervisor generation; an unavailable worker does not report a ready server.
Existing managed runtime settings and user model/cache locations are preserved.

## Validation

- Regression tests for zero eager launches, one launch for concurrent requests,
  failure propagation, shutdown during startup, and no startup after termination.
- Launch tests for private interpreter preference and safe development fallback.
- Local-provider integration tests for lazy inference and optional preload.
- Real named-pipe handshake and a trivial job through the bundled interpreter
  without repository paths or external Python on `PATH`.
- `uv run ruff check .`, full `uv run pytest`, Rust supervisor tests using Python
  3.13, and `uv run scons --dry-run`.
- Full package build and archive inspection when the build environment permits.

## Scope

This repair does not add OCR/transcription features or wire the dormant
`ModelManagementService` into all providers. Resource arbitration needs a separate
design: allocations must commit after actual loading and eviction/reaping must
wait for runtime unload acknowledgement. It cannot safely be activated by merely
removing entries from an in-memory dictionary.
