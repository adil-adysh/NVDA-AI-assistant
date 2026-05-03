use std::cell::RefCell;
#[cfg(test)]
use std::sync::atomic::{AtomicBool, Ordering};
#[cfg(test)]
use std::sync::{Mutex, OnceLock};
use windows::{
    core::{w, Result, PCWSTR},
    Win32::{
        Foundation::*,
        UI::WindowsAndMessaging::GetClientRect,
    },
};

use crate::app::ActivationPolicy;
use crate::host_dispatch::{self, DeliveryOutcome, HostCommand, WebViewState};
use crate::logger;
use crate::window::request_close_window;
use serde_json::Value;
use webview2_com::Microsoft::Web::WebView2::Win32::*;
use webview2_com::{
    AddScriptToExecuteOnDocumentCreatedCompletedHandler,
    CreateCoreWebView2ControllerCompletedHandler, CreateCoreWebView2EnvironmentCompletedHandler,
    NavigationCompletedEventHandler, WebMessageReceivedEventHandler,
};

use crate::ipc;

static mut WEBVIEW_ENVIRONMENT: Option<ICoreWebView2Environment> = None;
static mut WEBVIEW_CORE: Option<ICoreWebView2> = None;
thread_local! {
    static WEBVIEW_CONTROLLER: RefCell<Option<ICoreWebView2Controller>> = const { RefCell::new(None) };
}
#[cfg(test)]
static POST_WEB_MESSAGE_OVERRIDE: OnceLock<Mutex<Option<fn(&str) -> Result<()>>>> = OnceLock::new();
#[cfg(test)]
static TEST_CAPTURED_MESSAGES: OnceLock<Mutex<Vec<String>>> = OnceLock::new();
#[cfg(test)]
static TEST_CONTROLLER_READY: OnceLock<AtomicBool> = OnceLock::new();

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

enum WebViewEvent {
    WebUiReady,
    CloseHost,
    EscapePressed,
    Other,
}

fn parse_webview_event(payload: &Value) -> Option<WebViewEvent> {
    let event_name = payload
        .get("event")
        .and_then(Value::as_object)
        .and_then(|event| event.get("name"))
        .and_then(Value::as_str);

    match event_name {
        Some("web_ui_ready") => Some(WebViewEvent::WebUiReady),
        Some("close_host") => Some(WebViewEvent::CloseHost),
        Some("escape_pressed") => Some(WebViewEvent::EscapePressed),
        Some(_) => Some(WebViewEvent::Other),
        None => None,
    }
}

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

    if command.request_webview_focus || command.activation_policy == ActivationPolicy::ActivateAndFocus {
        let _ = focus_webview();
    }

    post_message_to_webview(controller, &command.message)?;
    Ok(DeliveryOutcome::Delivered)
}

fn flush_pending_messages() {
    let count = host_dispatch::pending_command_count();
    logger::info(&format!("FLUSH CALLED: queue_size={}", count));

    if host_dispatch::host_ready() {
        if let Some(controller) = current_controller() {
            let queued_commands = host_dispatch::take_pending_commands();
            logger::debug(&format!("Flushing {} queued host messages", count));
            let mut deferred_commands: Vec<HostCommand> = Vec::new();
            for command in queued_commands {
                logger::debug(&format!(
                    "Flushing queued message len={} activation_policy={:?} request_webview_focus={} preview={}",
                    command.message.len(),
                    command.activation_policy,
                    command.request_webview_focus,
                    logger::preview(&command.message, 160)
                ));
                match send_pending_command(&controller, command.clone()) {
                    Ok(DeliveryOutcome::Delivered) => {}
                    Ok(DeliveryOutcome::DeferredVisibility) => deferred_commands.push(command),
                    Err(err) => {
                        logger::error(&format!("Failed to flush queued host message: {:?}", err));
                        deferred_commands.push(command);
                    }
                }
            }
            if !deferred_commands.is_empty() {
                let deferred_count = deferred_commands.len();
                host_dispatch::requeue_pending_commands(deferred_commands);
                logger::info(&format!(
                    "Re-queued {} host message(s) pending a visible window",
                    deferred_count
                ));
            }
            logger::debug("flush_pending_messages completed, queue drained");
            return;
        }
    }

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

fn current_controller() -> Option<ICoreWebView2Controller> {
    WEBVIEW_CONTROLLER.with(|controller| controller.borrow().clone())
}

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

fn handle_js_event(message: &str, _hwnd: HWND) -> Result<()> {
    logger::debug(&format!("WebView JS event received: {}", message));
    let payload: Value = match serde_json::from_str(message) {
        Ok(value) => value,
        Err(err) => {
            logger::error(&format!("WebView JS event parse failed: {:?}", err));
            return Ok(());
        }
    };

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

pub fn resize_webview(hwnd: HWND) {
    if let Some(controller) = current_controller() {
        let mut rect = RECT::default();
        let _ = unsafe { GetClientRect(hwnd, &mut rect) };
        unsafe {
            controller.SetBounds(rect).ok();
        }
    }
}

pub fn focus_webview() -> bool {
    if let Some(controller) = current_controller() {
        match unsafe { controller.MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC) } {
            Ok(()) => {
                logger::debug("Moved focus into WebView");
                true
            }
            Err(error) => {
                logger::warn(&format!("Unable to move focus into WebView: {:?}", error));
                false
            }
        }
    } else {
        logger::debug("Skipped WebView focus move because controller is not ready");
        false
    }
}

pub(crate) fn post_host_command(message: &str, activation_policy: ActivationPolicy, request_webview_focus: bool) -> Result<()> {
    let queue_len_before = host_dispatch::pending_command_count();
    logger::debug(&format!(
        "QUEUE MESSAGE: controller_ready={} webview_ready={} queue_len_before={}",
        current_controller().is_some(),
        host_dispatch::is_webview_ready(),
        queue_len_before
    ));
    logger::info(&format!("WebView host command received: controller_ready={} webview_ready={} activation_policy={:?} request_webview_focus={} length={} message_preview={}", current_controller().is_some(), host_dispatch::is_webview_ready(), activation_policy, request_webview_focus, message.len(), message.chars().take(120).collect::<String>()));
    logger::debug(&format!(
        "WebView post_host_command called, message length={} controller_ready={} webview_ready={} preview={}",
        message.len(),
        current_controller().is_some(),
        host_dispatch::is_webview_ready(),
        logger::preview(message, 160)
    ));

    let pending_command = HostCommand {
        message: message.to_string(),
        activation_policy,
        request_webview_focus,
    };

    if host_dispatch::host_ready() {
        if let Some(controller) = current_controller() {
            match send_pending_command(&controller, pending_command.clone()) {
                Ok(DeliveryOutcome::Delivered) => {
                    logger::debug("WebView message sent immediately");
                    return Ok(());
                }
                Ok(DeliveryOutcome::DeferredVisibility) => {
                    logger::info("WebView host command deferred until the window becomes visible");
                }
                Err(err) => {
                    logger::warn(&format!("WebView send failed, queueing message: {:?}", err));
                }
            }
        }
    }

    logger::info("WebView controller or navigation not ready, queueing message");
    #[cfg(test)]
    {
        if test_controller_ready() {
            if let Some(mutex) = POST_WEB_MESSAGE_OVERRIDE.get() {
                let guard = mutex.lock().unwrap();
                if let Some(override_fn) = *guard {
                    return override_fn(message);
                }
            }
        }
    }

    host_dispatch::enqueue_pending_command(pending_command);
    Ok(())
}

pub(crate) fn notify_window_visible() {
    flush_pending_messages();
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, OnceLock};

    fn test_guard() -> std::sync::MutexGuard<'static, ()> {
        static TEST_MUTEX: OnceLock<Mutex<()>> = OnceLock::new();
        TEST_MUTEX.get_or_init(|| Mutex::new(())).lock().unwrap()
    }

    #[test]
    fn post_host_command_queues_message_when_controller_not_ready() {
        let _guard = test_guard();
        clear_pending_messages();
        assert_eq!(pending_message_count(), 0);

        post_host_command("test message", ActivationPolicy::NoActivate, false).expect("post_host_command should succeed");

        assert_eq!(pending_message_count(), 1);
    }

    #[test]
    fn post_host_command_queues_multiple_messages_when_controller_not_ready() {
        let _guard = test_guard();
        clear_pending_messages();
        assert_eq!(pending_message_count(), 0);

        post_host_command("first message", ActivationPolicy::NoActivate, false).expect("post_host_command should succeed");
        post_host_command("second message", ActivationPolicy::NoActivate, false).expect("post_host_command should succeed");

        assert_eq!(pending_message_count(), 2);
    }

    #[test]
    fn flush_pending_messages_drains_queue_when_controller_ready() {
        let _guard = test_guard();
        clear_pending_messages();
        clear_captured_messages();

        set_post_message_override(|message| {
            capture_message(message);
            Ok(())
        });

        post_host_command("queued message 1", ActivationPolicy::NoActivate, false).expect("post_host_command should succeed");
        post_host_command("queued message 2", ActivationPolicy::NoActivate, false).expect("post_host_command should succeed");

        assert_eq!(pending_message_count(), 2);

        flush_pending_messages();

        assert_eq!(pending_message_count(), 0);
        assert_eq!(
            captured_messages(),
            vec![
                "queued message 1".to_string(),
                "queued message 2".to_string()
            ]
        );
    }

    #[test]
    fn post_host_command_sends_immediately_when_test_controller_ready() {
        let _guard = test_guard();
        clear_pending_messages();
        clear_captured_messages();
        clear_test_controller_ready();

        set_test_controller_ready(true);
        set_post_message_override(|message| {
            capture_message(message);
            Ok(())
        });

        post_host_command("immediate message", ActivationPolicy::NoActivate, false).expect("post_host_command should succeed");

        assert_eq!(pending_message_count(), 0);
        assert_eq!(captured_messages(), vec!["immediate message".to_string()]);

        clear_test_controller_ready();
    }

    #[test]
    fn web_ui_ready_event_marks_webview_ready() {
        let _guard = test_guard();
        host_dispatch::set_webview_ready(false);

        handle_js_event(
            r#"{"schema":"nvda.ui_host","version":2,"type":"event","event":{"name":"web_ui_ready","payload":{}}}"#,
            HWND(std::ptr::null_mut()),
        )
        .expect("web_ui_ready event should succeed");

        assert!(is_webview_ready());
    }
}

pub fn init_webview(hwnd: HWND) -> Result<()> {
    unsafe {
        logger::info("Initializing WebView2...");
        logger::debug("WebView init_webview() starting environment creation");

        CreateCoreWebView2EnvironmentWithOptions(
            None,
            None,
            None,
            &CreateCoreWebView2EnvironmentCompletedHandler::create(Box::new(move |_hr: Result<()>, env: Option<ICoreWebView2Environment>| {
                logger::debug(&format!("Environment creation callback complete: hr={:?}", _hr));
                logger::info("Environment created");
                host_dispatch::set_webview_state(WebViewState::EnvironmentReady);

                let Some(env) = env else {
                    logger::error("WebView2 environment callback returned None");
                    return Ok(());
                };

                WEBVIEW_ENVIRONMENT = Some(env.clone());

                env.CreateCoreWebView2Controller(
                    hwnd,
                    &CreateCoreWebView2ControllerCompletedHandler::create(Box::new(move |_hr: Result<()>, controller: Option<ICoreWebView2Controller>| {
                        logger::debug(&format!("Controller creation callback complete: hr={:?}", _hr));
                        logger::info("Controller created");

                        let Some(controller) = controller else {
                        logger::error("WebView2 environment callback returned None");
                            return Ok(());
                        };

                        WEBVIEW_CONTROLLER.with(|slot| {
                            *slot.borrow_mut() = Some(controller.clone());
                        });
                        if host_dispatch::is_webview_ready() {
                            host_dispatch::set_webview_state(WebViewState::Ready);
                            logger::info("WebView host is ready");
                        } else {
                            host_dispatch::set_webview_state(WebViewState::ControllerReady);
                            logger::info("WebView controller ready");
                        }
                        maybe_transition_to_ready();
                        logger::info("WEBVIEW CONTROLLER SET");

                        let webview = match controller.CoreWebView2() {
                            Ok(webview) => webview,
                            Err(e) => {
                                logger::error(&format!("CoreWebView2 retrieval failed: {:?}", e));
                                return Ok(());
                            }
                        };

                        WEBVIEW_CORE = Some(webview.clone());

                        controller.SetIsVisible(true).unwrap_or_else(|e| {
                            logger::warn(&format!("SetIsVisible failed: {:?}", e));
                        });

                        let mut rect = RECT::default();
                        let _ = GetClientRect(hwnd, &mut rect);
                        controller.SetBounds(rect).unwrap_or_else(|e| {
                            logger::warn(&format!("SetBounds failed: {:?}", e));
                        });

                        webview
                            .AddScriptToExecuteOnDocumentCreated(
                                w!(r#"
                                    window.__sendHostEvent = payload => {
                                        window.chrome.webview.postMessage(JSON.stringify(payload));
                                    };
                                "#),
                                &AddScriptToExecuteOnDocumentCreatedCompletedHandler::create(
                                    Box::new(move |_hr: Result<()>, _script: String| {
                                        Ok(())
                                    }),
                                ),
                            )
                            .unwrap_or_else(|e| {
                                logger::error(&format!("AddScriptToExecuteOnDocumentCreated failed: {:?}", e));
                            });

                        let mut token = 0i64;
                        if let Err(e) = webview.add_WebMessageReceived(
                            &WebMessageReceivedEventHandler::create(Box::new(
                                move |_sender: Option<ICoreWebView2>,
                                      args: Option<ICoreWebView2WebMessageReceivedEventArgs>| {
                                    let Some(args) = args else {
                                        logger::error("WebMessageReceived args were None");
                                        return Ok(());
                                    };

                                    let mut message = windows::core::PWSTR::null();
                                    if let Err(e) = args.TryGetWebMessageAsString(&mut message) {
                                        logger::error(&format!("TryGetWebMessageAsString failed: {:?}", e));
                                        return Ok(());
                                    }

                                    let message = message.to_string().unwrap_or_default();
                                    logger::debug(&format!("JS -> host: {}", message));
                                    if let Err(err) = handle_js_event(&message, hwnd) {
                                        logger::error(&format!("Failed to handle JS event: {:?}", err));
                                    }
                                    Ok(())
                                },
                            )),
                            &mut token,
                        ) {
                            logger::error(&format!("add_WebMessageReceived failed: {:?}", e));
                        }

                        let mut nav_token = 0i64;
                        if let Err(e) = webview.add_NavigationCompleted(
                            &NavigationCompletedEventHandler::create(Box::new(move |_sender: Option<ICoreWebView2>, _args: Option<ICoreWebView2NavigationCompletedEventArgs>| {
                                logger::debug("Navigation completed");
                                let _ = focus_webview();
                                Ok(())
                            })),
                            &mut nav_token,
                        ) {
                            logger::error(&format!("add_NavigationCompleted failed: {:?}", e));
                        }

                        logger::info("WebView fully initialized, loading embedded host page");
                        let html = build_embedded_html();
                        logger::debug(&format!("Loading embedded UI ({} bytes)", html.len()));
                        let html_wide = to_wide(&html);
                        let ptr = PCWSTR(html_wide.as_ptr());
                        if let Err(e) = webview.NavigateToString(ptr) {
                            logger::error(&format!("WebView NavigateToString failed: {:?}", e));
                        } else {
                            host_dispatch::set_webview_state(WebViewState::NavigationStarted);
                            logger::info("Navigation started");
                        }

                        Ok(())
                    })),
                )
                .ok()
                .unwrap();

                Ok(())
            }))
        )
        .ok()
        .unwrap();
    }

    Ok(())
}
