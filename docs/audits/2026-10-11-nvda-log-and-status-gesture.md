# NVDA log review and provider status gesture

Reviewed the current and previous NVDA logs on October 11, 2026.

## Fixed

The model worker handshook successfully, then terminated after its watchdog
incorrectly classified the running NVDA parent as dead. This caused broken-pipe
errors during LiteRT model selection and exhausted the worker restart circuit
breaker. The watchdog called `win32process.OpenProcess`, which does not exist in
pywin32. It now calls `win32api.OpenProcess` and closes the query handle even if
the exit-code query fails. A real Windows process regression test reproduced the
failure before the fix and passes afterward.

Added the assistant-layer R command to announce the configured provider and
model. It reads the current configuration on each invocation, announces an empty
model as "Not selected", and never starts a worker/server or changes focus. The
script is available for assignment in NVDA Input Gestures; both layer help
messages and the command documentation include it.

## Other observations

The previous log contains access-denied errors renaming the installed AI
Assistant directory during add-on replacement. This is an installation/filesystem
failure; the log alone does not establish which process or permission caused it.
The active installation was not modified during this review.

Unrelated diagnostics include Tony's Enhancements failing during audio-session
enumeration, Task Switcher failing to read/remove its corrupt cache, and an NVDA
add-on-store scan-metadata parsing error. Browser accessibility COM warnings also
appear. Those components were not modified.

## Validation

The focused plugin/watchdog suite passed (103 tests and 18 subtests), Ruff passed,
and SCons produced the add-on. Package inspection confirmed the gesture and
watchdog fixes are included and no tests or Python bytecode are packaged.
Independent review found no actionable issues. Live testing after installing
the rebuilt add-on remains necessary to confirm behavior inside NVDA.
