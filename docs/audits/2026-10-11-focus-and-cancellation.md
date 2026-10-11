# Host focus, dismissal, and cancellation audit

## Required behavior

| Action | Window and keyboard policy |
| --- | --- |
| Explicitly open chat | Show the host and focus the composer. |
| Start or stream an inference | Leave the user's foreground application and keyboard focus alone. |
| Complete a response | Bring the host forward and focus the result content after rendering. |
| Escape in chat | Hide the host, preserving its conversation, draft, attachments, and active request. |
| Escape during input composition or an expanded select | Dismiss that interaction first. |
| Stop response | Cancel that request cooperatively, save its partial answer with `[Stopped]`, and avoid foreground activation. |
| Stop active requests from NVDA | Cancel outstanding chat, summary, and image requests, including queued presentation. |

The global Stop action is available from Tools → AI Assistant, the assignable `stopActiveRequests` script, and the assistant layer (`NVDA+Shift+A`, then `Q`). Escape does not invoke cancellation.

## Reproduced defects and repairs

- Native focus ran before command delivery, on every `ui_applied`, and during resize/navigation without a visibility/foreground check. Focus now requires the current activating command's acknowledgement, after two Svelte flushes. Dismissal invalidates pending acknowledgements and posted focus work. Queued commands already present at dismissal cannot reactivate the window.
- The native dismissal event lacked the required envelope ID and Python rejected it. Native close events now use complete version-2 envelopes.
- Progress changed a chat into a display view and requested status focus. Progress now updates status without replacing the view or requesting focus.
- Hidden streaming traffic incorrectly marked the Python lifecycle ready. Passive commands now preserve `HIDDEN`; an activating final response or explicit opening changes it.
- Reopening chat erased drafts, and preservation could retain another conversation's transcript. Preservation requires the same conversation and a live host process. A restarted host receives saved history.
- Chat had no Stop action. Each submission now has a request ID and cancellation token registered before its thread starts. Late chunks, stale stops, and old completions cannot affect a newer request. Latest request identities survive completion to prevent an older delayed request becoming current again.
- Cancelled provider/readiness errors could become normal error UI. Cancellation is checked around readiness, provider calls, and individual tool calls; wrapped failures become stopped turns. Shared providers and model servers remain open.
- A queued one-shot result could open after Stop, including after the outer callback had scheduled response speech. Deferred presentation retains cancellation ownership through speech, NVDA callbacks, and the host command queue, checking cancellation at delivery.
- Conversation changes during context retrieval could commit a submission to a different session. Expected conversation identity is revalidated under the session lock.

## Validation and limits

Regression tests exercise production Python, Rust, and TypeScript paths, including request registration, cancelled readiness, saved partial turns, conversation switches, queued result cancellation, speech-deferred presentation, correlated acknowledgements, dismissal generations, IME/select Escape, disconnected DOM targets, and reopened drafts/history.

Verification: full Python suite **865 passed, 2 skipped, 18 deselected, 60 subtests passed**; final focused UI/plugin/thread-boundary checks **158 passed, 18 subtests passed**; Web UI **40 passed**; host Rust **39 passed per library/binary target** plus `cargo check`; runtime supervisor **20 passed**; Ruff clean. SCons dry run and full packaging succeeded. Packaged-worker and exclusion tests **3 passed**. The 21.35 MiB add-on contains **1536 recursively inspected entries and one nested archive**, with no tests, fixtures, or bytecode; packaged Python and Web UI files match current sources. Final review found no remaining actionable regressions after its two findings were repaired.

Cancellation is cooperative: an already-running non-streaming provider request may continue until transport returns or times out. Subsequent output is suppressed. Completed tool side effects are not rolled back.

Live NVDA speech, foreground activation, and WebView2 keyboard behavior still require an installed NVDA session for interactive validation.
