use std::cell::RefCell;
use std::sync::{Mutex, OnceLock};
#[cfg(test)]
use std::sync::atomic::{AtomicBool, Ordering};
use windows::{
    core::{PCWSTR, Result, w},
    Win32::{
        Foundation::*,
        UI::WindowsAndMessaging::{GetClientRect, PostMessageW, WM_CLOSE},
    },
};

use crate::logger;
use serde_json::Value;
use webview2_com::Microsoft::Web::WebView2::Win32::*;
use webview2_com::{
    AddScriptToExecuteOnDocumentCreatedCompletedHandler,
    CreateCoreWebView2ControllerCompletedHandler,
    CreateCoreWebView2EnvironmentCompletedHandler,
    NavigationCompletedEventHandler,
    WebMessageReceivedEventHandler,
};

use crate::ipc;

static mut WEBVIEW_ENVIRONMENT: Option<ICoreWebView2Environment> = None;
static mut WEBVIEW_CORE: Option<ICoreWebView2> = None;
thread_local! {
    static WEBVIEW_CONTROLLER: RefCell<Option<ICoreWebView2Controller>> = const { RefCell::new(None) };
}
static PENDING_MESSAGES: OnceLock<Mutex<Vec<String>>> = OnceLock::new();

#[cfg(test)]
static POST_WEB_MESSAGE_OVERRIDE: OnceLock<Mutex<Option<fn(&str) -> Result<()>>>> = OnceLock::new();
#[cfg(test)]
static TEST_CAPTURED_MESSAGES: OnceLock<Mutex<Vec<String>>> = OnceLock::new();
#[cfg(test)]
static TEST_CONTROLLER_READY: OnceLock<AtomicBool> = OnceLock::new();

fn pending_messages() -> &'static Mutex<Vec<String>> {
    PENDING_MESSAGES.get_or_init(|| Mutex::new(Vec::new()))
}

#[cfg(test)]
pub(crate) fn pending_message_count() -> usize {
    pending_messages().lock().unwrap().len()
}

#[cfg(test)]
pub(crate) fn clear_pending_messages() {
    pending_messages().lock().unwrap().clear();
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
    let _ = TEST_CAPTURED_MESSAGES.get_or_init(|| Mutex::new(Vec::new())).lock().unwrap().clear();
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

fn flush_pending_messages() {
    let mut queue = pending_messages().lock().unwrap();
    let count = queue.len();
    logger::info(&format!("FLUSH CALLED: queue_size={}", count));

    if let Some(controller) = current_controller() {
        logger::debug(&format!("Flushing {} queued host messages", count));
        for message in queue.drain(..) {
            logger::debug(&format!("Flushing queued message: {}", message));
            if let Err(err) = post_message_to_webview(&controller, &message) {
                logger::error(&format!("Failed to flush queued host message: {:?}", err));
            }
        }
        logger::debug("flush_pending_messages completed, queue drained");
        return;
    }
    logger::info(&format!("flush_pending_messages: WebView controller not ready, queue size {}", count));

    #[cfg(test)]
    {
        if let Some(mutex) = POST_WEB_MESSAGE_OVERRIDE.get() {
            let guard = mutex.lock().unwrap();
            if let Some(override_fn) = *guard {
                logger::debug(&format!("Flushing {} queued host messages via test override", count));
                for message in queue.drain(..) {
                    logger::debug(&format!("Flushing queued message: {}", message));
                    if let Err(err) = override_fn(&message) {
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
    logger::debug(&format!("Rust: send_webview_message payload len={} message={}", message.len(), message));
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
    html = html.replace("<link rel=\"stylesheet\" href=\"host.css\" />", &style_block);
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

fn handle_js_event(message: &str, hwnd: HWND) -> Result<()> {
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
    let event_name = payload
        .get("event")
        .and_then(Value::as_object)
        .and_then(|event| event.get("name"))
        .and_then(Value::as_str);

    if schema != Some("nvda.ui_host") || message_type != Some("event") {
        logger::warn(&format!("WebView JS event ignored due to invalid schema/type: {:?}/{:?}", schema, message_type));
        return Ok(());
    }

    if let Some("close_host") | Some("escape_pressed") = event_name {
        unsafe {
            let _ = PostMessageW(Some(hwnd), WM_CLOSE, WPARAM(0), LPARAM(0));
        }
        return Ok(());
    }

    if event_name.is_some() {
        ipc::queue_ui_event(message.to_string());
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

pub fn post_host_command(message: &str) -> Result<()> {
    let queue_len_before = pending_messages().lock().unwrap().len();
    logger::debug(&format!(
        "QUEUE MESSAGE: controller_ready={} queue_len_before={}",
        current_controller().is_some(),
        queue_len_before
    ));
    logger::info(&format!("WebView host command received: controller_ready={} length={} message_preview={}", current_controller().is_some(), message.len(), message.chars().take(120).collect::<String>()));
    logger::debug(&format!("WebView post_host_command called, message length={} controller_ready={} message={}", message.len(), current_controller().is_some(), message));
    if let Some(controller) = current_controller() {
        match post_message_to_webview(&controller, message) {
            Ok(()) => {
                logger::debug("WebView message sent immediately");
                return Ok(());
            }
            Err(err) => {
                logger::warn(&format!("WebView send failed, queueing message: {:?}", err));
                let mut queue = pending_messages().lock().unwrap();
                queue.push(message.to_string());
                logger::debug(&format!("WebView queue size after enqueue: {}", queue.len()));
                return Ok(());
            }
        }
    }

    logger::info("WebView controller not ready, queueing message");
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

    let mut queue = pending_messages().lock().unwrap();
    queue.push(message.to_string());
    Ok(())
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

        post_host_command("test message").expect("post_host_command should succeed");

        assert_eq!(pending_message_count(), 1);
    }

    #[test]
    fn post_host_command_queues_multiple_messages_when_controller_not_ready() {
        let _guard = test_guard();
        clear_pending_messages();
        assert_eq!(pending_message_count(), 0);

        post_host_command("first message").expect("post_host_command should succeed");
        post_host_command("second message").expect("post_host_command should succeed");

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

        post_host_command("queued message 1").expect("post_host_command should succeed");
        post_host_command("queued message 2").expect("post_host_command should succeed");

        assert_eq!(pending_message_count(), 2);

        flush_pending_messages();

        assert_eq!(pending_message_count(), 0);
        assert_eq!(captured_messages(), vec!["queued message 1".to_string(), "queued message 2".to_string()]);
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

        post_host_command("immediate message").expect("post_host_command should succeed");

        assert_eq!(pending_message_count(), 0);
        assert_eq!(captured_messages(), vec!["immediate message".to_string()]);

        clear_test_controller_ready();
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

                        let controller_clone = controller.clone();
                        let mut nav_token = 0i64;
                        if let Err(e) = webview.add_NavigationCompleted(
                            &NavigationCompletedEventHandler::create(Box::new(move |_sender: Option<ICoreWebView2>, _args: Option<ICoreWebView2NavigationCompletedEventArgs>| {
                                logger::debug("Navigation completed");
                                controller_clone.MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC).ok();
                                flush_pending_messages();
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
                        }

                        flush_pending_messages();
                        logger::info("Navigation started");

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
