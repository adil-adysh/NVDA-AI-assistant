# Architecture

## UI Host Integration

The NVDA add-on uses a clean host boundary to separate rendering intent from internal use-case logic.

### Add-on side

- `addon/globalPlugins/AI-assistant/ui/host_protocol.py` defines the JSON command/response envelope.
- `addon/globalPlugins/AI-assistant/ui/host_interface.py` defines the renderer contract.
- `addon/globalPlugins/AI-assistant/ui/adapter.py` selects between:
  - host renderer (`HostRenderer`)
  - native NVDA renderer (`NativeRenderer`)
- `addon/globalPlugins/AI-assistant/ui/host_process.py` launches the external host binary if needed.
- `addon/globalPlugins/AI-assistant/plugin/presenter.py` maps `UseCaseResult` into generic UI payloads.

### Host side

- `nvda_ui_host/src/protocol.rs` owns the normalized v2 envelope and legacy compatibility parser.
- `nvda_ui_host/src/ipc.rs` provides a named pipe server on `\\.\pipe\nvda_ai_assistant_ui` and forwards raw frames to the app layer.
- `nvda_ui_host/src/app.rs` validates inbound messages, returns typed `ack` or `error` replies, and normalizes all UI work into the v2 envelope.
- `nvda_ui_host/src/window.rs` owns the bounded UI dispatch queue and drains it on the window thread via `WM_APP`.
- `nvda_ui_host/src/webview.rs` implements generic WebView rendering, queue flushing, and JS event reporting.

## Packaging

- The external host binary is built from `nvda_ui_host/`.
- The package includes `addon/globalPlugins/AI-assistant/ui_host/nvda_ui_host.exe`.
- `sconstruct` now copies the built host executable into the add-on bundle when packaging.

## Design principles

- Protocol payloads are generic and UI-focused.
- Addon-specific semantics stay inside the add-on layer.
- The host is a renderer backend only; it does not own prompt or use-case logic.
- Native UI fallback remains the default when the host is unavailable.
- WebView2 calls stay on the UI thread; background work reaches the UI only through the bounded window dispatch queue.
