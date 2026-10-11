# Startup settings and UI wiring repair

Runtime settings now offer one startup policy for each managed local provider:
start when needed (default), prepare the background worker, or start the local
server. Only the active provider's policy runs at the next NVDA startup.
Worker preparation does not start a server or require its installation. Server
startup uses the normal readiness path. Legacy saved booleans retain their
meaning. Each choice has visible help and an accessible name explaining its
effect. Preparing the worker and starting a server do not promise loaded model
weights.

Reproduced UI defects repaired in this pass:

- Failed provider/model/thinking bridge sends left controls permanently pending.
  Controls now recover, preserve relevant drafts, and announce the failure.
  Bridge exceptions become failed sends.
- Failed conversation opens changed the selected conversation. Selection now
  changes only after a successful send.
- Clipboard fallback removed the focused textarea without restoring keyboard
  focus. The previous connected element now regains focus.
- Global keyboard submission captured the file input before chat mounted.
  It now resolves the current input when the shortcut runs.
- Global shortcuts consumed already-handled or IME composition events; composer
  Enter also submitted during composition. These events are now respected.
- Background error handling inspected wx owners on worker threads. Owner checks
  now run only in the UI callback.
- Cancelled background work still delivered already-queued results. Result/error
  callbacks now observe cancellation while cleanup remains available.
- Settings catalog refresh erased unsaved model names and accepted stale refresh
  completions. Drafts now survive refresh/provider changes, and completion uses
  a refresh generation. Catalog loading does not disable model-name editing.
- Global Top-p accepted values above one. Validation now enforces the range 0–1.
- Provider selection through the gesture layer started a server immediately,
  bypassing lazy inference startup. Selection now preserves lazy server launch.
- Conversation reset retained the previous turn's processing state. It now
  releases the composer.
- Conversation summary arrival could clear an authoritative active ID, including
  newly opened empty conversations. Summary updates now affect presentation
  state without discarding the selected ID.
- Late stream and message events could select a previous conversation or release
  another conversation's active turn. Incremental updates are scoped to the
  displayed conversation, and unmatched aborts cannot clear processing.

Tests use real wx controls, production TypeScript action/command/transcript
code with browser and reactive-state boundaries replaced, and deterministic
background completion. Live NVDA speech/focus and real inference remain manual
validation paths.

Validation after repairs: 839 Python tests passed, 2 skipped, 18 deselected,
with 60 subtests; 21 Web UI regression tests passed; Ruff passed; Rust host
checking passed and all 20 supervisor tests passed. The full SCons release
package built successfully. Both private-bundle and extracted-add-on worker
smoke tests passed outside the checkout with no external Python path.
