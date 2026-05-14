// WebView static state, lifecycle transitions, and test infrastructure.
// Included into webview.rs — shares its imports and namespace.

// ── Global / thread-local state ────────────────────────────────────────

static mut WEBVIEW_ENVIRONMENT: Option<ICoreWebView2Environment> = None;
static mut WEBVIEW_CORE: Option<ICoreWebView2> = None;
thread_local! {
    static WEBVIEW_CONTROLLER: RefCell<Option<ICoreWebView2Controller>> = const { RefCell::new(None) };
}

// ── Test overrides ────────────────────────────────────────────────────

#[cfg(test)]
static POST_WEB_MESSAGE_OVERRIDE: OnceLock<Mutex<Option<fn(&str) -> Result<()>>>> = OnceLock::new();
#[cfg(test)]
static TEST_CAPTURED_MESSAGES: OnceLock<Mutex<Vec<String>>> = OnceLock::new();
#[cfg(test)]
static TEST_CONTROLLER_READY: OnceLock<AtomicBool> = OnceLock::new();

// ── Ready-transition logic ────────────────────────────────────────────

fn maybe_transition_to_ready() {
    let state = host_dispatch::current_webview_state();
    if state == WebViewState::Ready {
        flush_pending_messages();
        return;
    }
    if state == WebViewState::ControllerReady && host_dispatch::is_webview_ready() {
        host_dispatch::set_webview_state(WebViewState::Ready);
        logger::info("WebView host is ready");
        flush_pending_messages();
    } else if state == WebViewState::WebUiReady && current_controller().is_some() {
        host_dispatch::set_webview_state(WebViewState::Ready);
        logger::info("WebView host is ready");
        flush_pending_messages();
    }
}

// ── Event classification ──────────────────────────────────────────────

enum WebViewEvent {
    WebUiReady,
    CloseHost,
    Other,
}

fn parse_webview_event(payload: &serde_json::Value) -> Option<WebViewEvent> {
    let event_name = payload
        .get("event")
        .and_then(serde_json::Value::as_object)
        .and_then(|event| event.get("name"))
        .and_then(serde_json::Value::as_str);

    match event_name {
        Some("web_ui_ready") => Some(WebViewEvent::WebUiReady),
        Some("close_host") => Some(WebViewEvent::CloseHost),
        Some(_) => Some(WebViewEvent::Other),
        None => None,
    }
}

// ── Controller access ─────────────────────────────────────────────────

fn current_controller() -> Option<ICoreWebView2Controller> {
    WEBVIEW_CONTROLLER.with(|controller| controller.borrow().clone())
}

// ── Test helpers ──────────────────────────────────────────────────────

#[cfg(test)]
pub(crate) fn is_webview_ready() -> bool {
    host_dispatch::is_webview_ready()
}

#[cfg(test)]
pub(crate) fn pending_message_count() -> usize {
    host_dispatch::pending_command_count()
}

pub(crate) fn clear_pending_messages() {
    host_dispatch::clear_pending_commands();
}

#[cfg(test)]
pub(crate) fn set_post_message_override(override_fn: fn(&str) -> Result<()>) {
    let mutex = POST_WEB_MESSAGE_OVERRIDE.get_or_init(|| Mutex::new(None));
    let mut guard = mutex.lock().unwrap();
    *guard = Some(override_fn);
}

#[cfg(test)]
pub(crate) fn clear_captured_messages() {
    let _ = TEST_CAPTURED_MESSAGES
        .get_or_init(|| Mutex::new(Vec::new()))
        .lock()
        .unwrap()
        .clear();
}

#[cfg(test)]
pub(crate) fn capture_message(message: &str) {
    let captured = TEST_CAPTURED_MESSAGES.get_or_init(|| Mutex::new(Vec::new()));
    captured.lock().unwrap().push(message.to_string());
}

#[cfg(test)]
pub(crate) fn captured_messages() -> Vec<String> {
    TEST_CAPTURED_MESSAGES
        .get()
        .map(|m| m.lock().unwrap().clone())
        .unwrap_or_default()
}

#[cfg(test)]
pub(crate) fn set_test_controller_ready(value: bool) {
    TEST_CONTROLLER_READY
        .get_or_init(|| AtomicBool::new(false))
        .store(value, Ordering::SeqCst);
}

#[cfg(test)]
pub(crate) fn clear_test_controller_ready() {
    if let Some(flag) = TEST_CONTROLLER_READY.get() {
        flag.store(false, Ordering::SeqCst);
    }
}

#[cfg(test)]
pub(crate) fn test_controller_ready() -> bool {
    TEST_CONTROLLER_READY
        .get()
        .map(|flag| flag.load(Ordering::SeqCst))
        .unwrap_or(false)
}
