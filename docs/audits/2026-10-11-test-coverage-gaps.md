# NVDA failures and missed test boundaries

## Latest log evidence

After the NVDA restart at approximately 19:54, the earlier worker restart loop
is absent. LiteRT startup and image description instead fail because the worker
tries to launch `runtimes/litert-lm-0.15.0/python.exe`. The installed runtime is
actually at `runtimes/litert-lm/0.15.0/python.exe`, which exists. The installer
and NVDA adapter resolve the nested layout; the worker had independently encoded
a different default. The adapter's commands omitted the resolved paths, exposing
this difference at the process boundary.

The current log also contains unrelated Tony's Enhancements audio enumeration,
Task Switcher cache, NVDA add-on-store scan metadata, and browser editable-text
COM failures. These are not evidence of this add-on's runtime failing.

## Why previous tests passed

| Gap | Evidence | Consequence |
| --- | --- | --- |
| Parent watchdog not exercised | In-process heartbeat tests construct WorkerServer with the default parent PID of zero; liveness tests kill the spawned worker immediately. | They check heartbeat replies/death detection, not whether a healthy worker survives its own parent check. |
| Smoke test shorter than watchdog interval | The original packaged smoke test did a handshake, status query, and small local transfer, then stopped. | It could complete before the worker's first 0.5-second parent check. A successful handshake did not establish sustained health. |
| Independent path mocks | Runtime adapter tests replace the path resolver with `/fake/runtime`; executor tests replace the native process launcher. | Each layer can pass with incompatible runtime layouts. No assertion compared installer and worker paths. |
| Alternate test branch | Several adapter tests patch `_run_litert_cli`, selecting a compatibility branch instead of the production worker route. | Those tests verify local CLI arguments, not commands actually sent through the worker. |
| Packaging optional in unit CI | Python quality runs pytest and SCons dry-run; smoke tests skip without package artifacts. Build/release previously built/uploaded without running these tests. | Neither job guaranteed that the built package was exercised before publication. |

The previous parent check also swallowed every exception and returned false,
turning a nonexistent API call into a misleading "parent no longer alive"
message. Ruff detects syntax/import problems, but does not validate arbitrary
attributes of native extension modules.

## Changes made

- Corrected the worker's default layout and pass the adapter's resolved Python,
  registry, and runtime version to worker commands. This also fixes non-default
  versions in model import/delete/rename operations.
- Added a resolver contract test and startup/restart tests through the real
  adapter, worker handler, and executor, replacing only native process launch.
  All three tests failed against the previous code and passed with the fixes.
- Extended packaged smoke coverage to require healthy replies beyond 1.5 seconds
  of worker uptime, spanning multiple parent-watchdog checks.
- Added a required-artifact mode which fails instead of skipping missing bundles
  and packages. The build/release workflow now prepares the pinned NVDA checkout
  and locked uv environment and runs these checks after building, before upload.
- Retained the real Windows parent-process API tests added in the previous fix.

## Validation and remaining limits

The full default suite passed: 875 tests, 60 subtests, two skips and 18 excluded
NVDA integration tests. The required package gate passed all seven tests with
no skips. Ruff passed, the workflow YAML parsed, and SCons rebuilt the add-on.
The changed GitHub workflow has not been executed remotely in this session.

These checks do not replace live NVDA testing. Before release, exercise gestures,
startup modes, inference, cancellation, result focus, Escape, and upgrade/shutdown
in a running NVDA instance. Keep heavyweight provider/network substitutes narrow;
keep real path resolution, native API lookup, serialization, and producer/consumer
code together wherever they can run outside NVDA.
