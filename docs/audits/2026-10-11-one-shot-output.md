# One-shot response output

Added the approved three-mode preference under Settings → Behavior & Output:

- Display only (default): immediately display/focus the result without an
  explicit full-answer announcement; normal NVDA focus feedback remains.
- Speak, then display: announce the answer, then display it after speech
  completion or cancellation of speech. AI-request cancellation still suppresses
  deferred presentation.
- Speak only: announce the answer without launching the UI host or changing focus.

Python settings validate/persist the preference. The presenter selects the mode;
the adapter implements speech/window delivery without changing chat, errors,
progress, or native presentation protocols. No Rust/Svelte behavior was added.

The latest successful one-shot view is retained in memory for the current add-on
session. Show last result is available in Tools, Input Gestures, and assistant
layer L. It always opens the result regardless of the output preference. Shutdown
clears the retained view. A presentation generation prevents an older speech
callback from reopening its result after a newer presentation or explicit reopen.
Result action payloads remain reusable when reopening. Each pending result owns
its payloads until successful delivery atomically activates them, preserving the
previous result on cancellation and avoiding overlap between queued responses.

Validation: 899 tests and 60 subtests passed, with two skips and 18 excluded NVDA
integration tests. Ruff passed; SCons rebuilt the package. Tests exercise real
YAML persistence and wx choices, all output modes, HTML speech extraction,
cancellation before delivery, retained-result reopening, deferred-display races,
and real pinned NVDA callback/extension-point definitions for speech completion,
speech cancellation, and speech-off behavior. Packaged code and test/bytecode
exclusions were verified. Live NVDA behavior should be confirmed after installing.
