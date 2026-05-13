// WebView event handling — parses JS messages and dispatches to IPC/window.
// Included into webview.rs — shares its imports and namespace.

/// Parse and handle an incoming JavaScript event from the WebView.
fn handle_js_event(message: &str, _hwnd: HWND) -> Result<()> {
    let payload: Value = match serde_json::from_str(message) {
        Ok(value) => value,
        Err(err) => {
            logger::error(&format!("WebView JS event parse failed: {:?}", err));
            return Ok(());
        }
    };

    // Forward JS console.log/warn/error to the Rust log file
    let msg_type = payload.get("type").and_then(Value::as_str);
    if msg_type == Some("log") {
        let level = payload.get("level").and_then(Value::as_str).unwrap_or("log");
        let js_message = payload.get("message").and_then(Value::as_str).unwrap_or("");
        let line = format!("[WEBUI] {}", js_message);
        match level {
            "error" => logger::error(&line),
            "warn" => logger::warn(&line),
            _ => logger::info(&line),
        }
        return Ok(());
    }

    let schema = payload.get("schema").and_then(Value::as_str);
    let message_type = payload.get("type").and_then(Value::as_str);

    if schema != Some("nvda.ui_host") || message_type != Some("event") {
        logger::warn(&format!(
            "WebView JS event ignored due to invalid schema/type: {:?}/{:?}",
            schema, message_type
        ));
        return Ok(());
    }

    let event = parse_webview_event(&payload);
    match event {
        Some(WebViewEvent::WebUiReady) => {
            logger::info("WebView UI reported ready");
            host_dispatch::set_webview_ready(true);
            if host_dispatch::current_webview_state() == WebViewState::ControllerReady {
                host_dispatch::set_webview_state(WebViewState::Ready);
                logger::info("WebView host is ready");
            } else {
                host_dispatch::set_webview_state(WebViewState::WebUiReady);
            }
            maybe_transition_to_ready();
        }
        Some(WebViewEvent::CloseHost) | Some(WebViewEvent::EscapePressed) => {
            logger::info("WebView close event received, requesting host close");
            if let Err(dispatch_error) = request_close_window("user_escape") {
                logger::error(&format!("Failed to request host close from WebView event: {:?}", dispatch_error));
            }
        }
        Some(WebViewEvent::Other) => {
            ipc::queue_ui_event(message.to_string());
        }
        None => {
            logger::warn("WebView JS event ignored due to missing event name");
        }
    }

    Ok(())
}
