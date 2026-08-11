// WebView message delivery pipeline: send, flush, embed assets.
// Included into webview.rs — shares its imports and namespace.

// ── Asset embedding ───────────────────────────────────────────────────

const HOST_HTML: &str = include_str!("../assets/host.html");
const HOST_JS: &str = include_str!("../assets/host.js");
const HOST_CSS: &str = include_str!("../assets/host.css");

fn build_embedded_html() -> String {
    let mut html = HOST_HTML.to_string();

    let style_block = format!("<style>{}</style>", HOST_CSS);
    html = html.replace(
        "<link rel=\"stylesheet\" href=\"host.css\" />",
        &style_block,
    );
    html = html.replace("<link rel=\"stylesheet\" href=\"host.css\"/>", &style_block);
    html = html.replace("<link rel=\"stylesheet\" href=\"host.css\">", &style_block);

    let script_block = format!("<script>{}</script>", HOST_JS);
    html = html.replace("<script src=\"host.js\"></script>", &script_block);
    html = html.replace("<script src=\"host.js\"></script >", &script_block);

    if !html.contains("<style>") {
        if let Some(index) = html.find("</head>") {
            html.insert_str(index, &style_block);
        }
    }

    if !html.contains("<script>") {
        if let Some(index) = html.rfind("</body>") {
            html.insert_str(index, &script_block);
        }
    }

    html
}

fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}

// ── Message delivery ──────────────────────────────────────────────────

fn send_pending_command(controller: &ICoreWebView2Controller, command: HostCommand) -> Result<DeliveryOutcome> {
    if !host_dispatch::window_ready_for_delivery(
        command.activation_policy,
        crate::window::is_window_visible,
        crate::window::should_activate_visible_window,
        crate::window::try_activate_window,
    ) {
        logger::info(&format!(
            "Deferring host command until window is visible activation_policy={:?} request_webview_focus={} preview={}",
            command.activation_policy,
            command.request_webview_focus,
            logger::preview(&command.message, 160)
        ));
        return Ok(DeliveryOutcome::DeferredVisibility);
    }

    // When ActivateAndFocus brings the window forward, wndproc's WM_SETFOCUS
    // handler already calls focus_webview(). Skip the duplicate call here to
    // avoid a spurious "parameter is incorrect" warning when the WebView2
    // controller hasn't finished compositing yet.
    if command.request_webview_focus {
        let _ = focus_webview();
    }

    post_message_to_webview(controller, &command.message)?;
    Ok(DeliveryOutcome::Delivered)
}

fn send_webview_message(webview: &ICoreWebView2, message: &str) -> Result<()> {
    let mut wide: Vec<u16> = message.encode_utf16().collect();
    wide.push(0);
    let ptr = PCWSTR(wide.as_ptr());
    logger::debug(&format!(
        "Rust: send_webview_message payload len={} preview={}",
        message.len(),
        logger::preview(message, 160)
    ));
    let result = unsafe { webview.PostWebMessageAsString(ptr) };
    logger::debug(&format!("Rust: WebView send result: {:?}", result));
    result
}

fn post_message_to_webview(controller: &ICoreWebView2Controller, message: &str) -> Result<()> {
    logger::debug("SENDING TO WEBVIEW");
    #[cfg(test)]
    {
        if let Some(mutex) = POST_WEB_MESSAGE_OVERRIDE.get() {
            let guard = mutex.lock().unwrap();
            if let Some(override_fn) = *guard {
                return override_fn(message);
            }
        }
    }

    let webview = unsafe { controller.CoreWebView2()? };
    send_webview_message(&webview, message)
}

fn flush_pending_messages() {
    if host_dispatch::host_ready() {
        if let Some(controller) = current_controller() {
            host_dispatch::flush_pending_commands(
                |command| send_pending_command(&controller, command),
                |_, err| {
                    logger::error(&format!("Failed to flush queued host message: {:?}", err));
                },
            );
            return;
        }
    }

    let count = host_dispatch::pending_command_count();
    logger::info(&format!(
        "flush_pending_messages: WebView not ready, queue size {}",
        count
    ));

    #[cfg(test)]
    {
        if let Some(mutex) = POST_WEB_MESSAGE_OVERRIDE.get() {
            let guard = mutex.lock().unwrap();
            if let Some(override_fn) = *guard {
                logger::debug(&format!(
                    "Flushing {} queued host messages via test override",
                    count
                ));
                let queued_commands = host_dispatch::take_pending_commands();
                for command in queued_commands {
                    logger::debug(&format!(
                        "Flushing queued message len={} preview={}",
                        command.message.len(),
                        logger::preview(&command.message, 160)
                    ));
                    if let Err(err) = override_fn(&command.message) {
                        logger::error(&format!("Failed to flush queued host message: {:?}", err));
                    }
                }
            }
        }
    }
}
