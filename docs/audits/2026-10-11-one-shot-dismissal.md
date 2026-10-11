# One-shot result dismissal

The NVDA and UI-host logs around 20:05:40 show the Web UI emitting `close_host`,
the native window hiding, and Python receiving `user_dismissed`. NVDA then
continues navigating the host document and its Close button. Later Close events
are ignored because the host's state is already Hidden. This locates the failure
after event delivery, at the visibility/focus boundary.

The old hide path only hid the outer HWND. The WebView controller remained
visible to accessibility clients, and no explicit foreground restoration was
performed. The real WebView regression reproduces the first condition: calling
ShowWindow(SW_HIDE) leaves controller.IsVisible true.

## Repair

- Hide the WebView controller as well as its outer window; restore controller
  visibility before showing a later result or reopening chat.
- Remember the application interrupted by host activation and return foreground
  focus to its still-valid, visible window on dismissal. Background dismissal
  never steals focus from another application.
- Post dismissal from WebView callbacks and process it on the native message
  loop after the callback returns.
- Mark the host Closing before visibility changes, fencing synchronous focus
  callbacks. Soft dismissal still preserves streaming and command delivery.
- Use the same visibility/focus cleanup for native/programmatic close.

## Validation

Ran a real interactive WebView2 test: render a one-shot result, click the actual
DOM Close button, render another result, and dismiss through the native Escape
path. It verifies native and controller visibility, foreground restoration, and
reopening. The test passed. Rust library tests passed (42); Cargo check passed.
Focused Python UI/plugin tests passed (155 tests, 18 subtests), and Ruff passed.
Independent review found no actionable issues.

The interactive test is excluded from ordinary headless runs because it requires
a Windows desktop and WebView2. Run it explicitly before releasing focus changes:

```powershell
cargo test --manifest-path nvda_ui_host/Cargo.toml --lib real_one_shot_close_and_escape_hide_webview_and_reopen -- --ignored
```

The test runs an isolated host window without starting the fixed-name IPC
listeners, so it cannot send commands to the installed NVDA host. Its assertions
cover real native/WebView state; live NVDA speech and browse-mode behavior still
need confirmation after installing the rebuilt add-on.
