use std::cell::RefCell;
use std::sync::{Mutex, OnceLock};
#[cfg(test)]
use std::sync::atomic::{AtomicBool, Ordering};
use windows::{
    core::{PCWSTR, Result, w},
    Win32::{
        Foundation::*,
        UI::WindowsAndMessaging::GetClientRect,
    },
};

use webview2_com::Microsoft::Web::WebView2::Win32::*;
use webview2_com::{
    AddScriptToExecuteOnDocumentCreatedCompletedHandler,
    CreateCoreWebView2ControllerCompletedHandler,
    CreateCoreWebView2EnvironmentCompletedHandler,
    NavigationCompletedEventHandler,
    WebMessageReceivedEventHandler,
};

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
    eprintln!("flush_pending_messages called, queue size {}", count);

    if let Some(controller) = current_controller() {
        eprintln!("Flushing {} queued host messages", count);
        for message in queue.drain(..) {
            eprintln!("Flushing queued message: {}", message);
            if let Err(err) = post_message_to_webview(&controller, &message) {
                eprintln!("Failed to flush queued host message: {:?}", err);
            }
        }
        eprintln!("flush_pending_messages completed, queue drained");
        return;
    }
    eprintln!("flush_pending_messages: WebView controller not ready, queue size {}", count);

    #[cfg(test)]
    {
        if let Some(mutex) = POST_WEB_MESSAGE_OVERRIDE.get() {
            let guard = mutex.lock().unwrap();
            if let Some(override_fn) = *guard {
                eprintln!("Flushing {} queued host messages via test override", count);
                for message in queue.drain(..) {
                    eprintln!("Flushing queued message: {}", message);
                    if let Err(err) = override_fn(&message) {
                        eprintln!("Failed to flush queued host message: {:?}", err);
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
    println!("Rust: send_webview_message payload len={} message={}", message.len(), message);
    let result = unsafe { webview.PostWebMessageAsString(ptr) };
    println!("Rust: WebView send result: {:?}", result);
    result
}

fn current_controller() -> Option<ICoreWebView2Controller> {
    WEBVIEW_CONTROLLER.with(|controller| controller.borrow().clone())
}

fn post_message_to_webview(controller: &ICoreWebView2Controller, message: &str) -> Result<()> {
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
    eprintln!("WebView post_host_command called, message length={} controller_ready={} message={}", message.len(), current_controller().is_some(), message);
    if let Some(controller) = current_controller() {
        match post_message_to_webview(&controller, message) {
            Ok(()) => {
                eprintln!("WebView message sent immediately");
                return Ok(());
            }
            Err(err) => {
                eprintln!("WebView send failed, queueing message: {:?}", err);
                let mut queue = pending_messages().lock().unwrap();
                queue.push(message.to_string());
                eprintln!("WebView queue size after enqueue: {}", queue.len());
                return Ok(());
            }
        }
    }

    eprintln!("WebView controller not ready, queueing message");
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
        println!("Initializing WebView2...");
        println!("WebView init_webview() starting environment creation");

        CreateCoreWebView2EnvironmentWithOptions(
            None,
            None,
            None,
            &CreateCoreWebView2EnvironmentCompletedHandler::create(Box::new(move |_hr: Result<()>, env: Option<ICoreWebView2Environment>| {
                println!("Environment creation callback complete: hr={:?}", _hr);
                println!("Environment created");

                let Some(env) = env else {
                    eprintln!("WebView2 environment callback returned None");
                    return Ok(());
                };

                WEBVIEW_ENVIRONMENT = Some(env.clone());

                env.CreateCoreWebView2Controller(
                    hwnd,
                    &CreateCoreWebView2ControllerCompletedHandler::create(Box::new(move |_hr: Result<()>, controller: Option<ICoreWebView2Controller>| {
                        println!("Controller creation callback complete: hr={:?}", _hr);
                        println!("Controller created");

                        let Some(controller) = controller else {
                            eprintln!("WebView2 controller callback returned None");
                            return Ok(());
                        };

                        WEBVIEW_CONTROLLER.with(|slot| {
                            *slot.borrow_mut() = Some(controller.clone());
                        });

                        let webview = match controller.CoreWebView2() {
                            Ok(webview) => webview,
                            Err(e) => {
                                eprintln!("CoreWebView2 retrieval failed: {:?}", e);
                                return Ok(());
                            }
                        };

                        WEBVIEW_CORE = Some(webview.clone());

                        controller.SetIsVisible(true).unwrap_or_else(|e| {
                            eprintln!("SetIsVisible failed: {:?}", e);
                        });

                        let mut rect = RECT::default();
                        let _ = GetClientRect(hwnd, &mut rect);
                        controller.SetBounds(rect).unwrap_or_else(|e| {
                            eprintln!("SetBounds failed: {:?}", e);
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
                                eprintln!("AddScriptToExecuteOnDocumentCreated failed: {:?}", e);
                            });

                        let mut token = 0i64;
                        if let Err(e) = webview.add_WebMessageReceived(
                            &WebMessageReceivedEventHandler::create(Box::new(
                                move |_sender: Option<ICoreWebView2>,
                                      args: Option<ICoreWebView2WebMessageReceivedEventArgs>| {
                                    let Some(args) = args else {
                                        eprintln!("WebMessageReceived args were None");
                                        return Ok(());
                                    };

                                    let mut message = windows::core::PWSTR::null();
                                    if let Err(e) = args.TryGetWebMessageAsString(&mut message) {
                                        eprintln!("TryGetWebMessageAsString failed: {:?}", e);
                                        return Ok(());
                                    }

                                    let message = message.to_string().unwrap_or_default();
                                    println!("JS -> host: {}", message);
                                    match serde_json::from_str::<serde_json::Value>(&message) {
                                        Ok(value) => println!("JS event payload: {}", value),
                                        Err(error) => eprintln!("JS event parse failed: {:?}", error),
                                    }
                                    Ok(())
                                },
                            )),
                            &mut token,
                        ) {
                            eprintln!("add_WebMessageReceived failed: {:?}", e);
                        }

                        let controller_clone = controller.clone();
                        let mut nav_token = 0i64;
                        if let Err(e) = webview.add_NavigationCompleted(
                            &NavigationCompletedEventHandler::create(Box::new(move |_sender: Option<ICoreWebView2>, _args: Option<ICoreWebView2NavigationCompletedEventArgs>| {
                                println!("Navigation completed");
                                controller_clone.MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC).ok();
                                flush_pending_messages();
                                Ok(())
                            })),
                            &mut nav_token,
                        ) {
                            eprintln!("add_NavigationCompleted failed: {:?}", e);
                        }

                        println!("WebView fully initialized, navigating initial HTML");
                        if let Err(e) = webview.NavigateToString(
                            w!(r#"
                                <!DOCTYPE html>
                                <html lang="en">
                                <head>
                                    <meta charset="UTF-8">
                                    <title>NVDA UI Host</title>
                                    <style>
                                        body { font-family: Arial, sans-serif; margin: 0; padding: 16px; background: #f8f8f8; color: #111; }
                                        #status { margin-bottom: 12px; padding: 10px; border-radius: 6px; background: #fff; border: 1px solid #ddd; }
                                        #content { min-height: 220px; padding: 12px; border-radius: 6px; background: #fff; border: 1px solid #ddd; overflow-wrap: break-word; white-space: pre-wrap; }
                                        .toolbar { margin-top: 14px; }
                                        button { margin-right: 10px; padding: 8px 14px; font-size: 0.95rem; }
                                    </style>
                                </head>
                                <body>
                                    <div id="status">Waiting for host command...</div>
                                    <div id="content">No content received yet.</div>
                                    <div class="toolbar">
                                        <button id="copy-text">Copy text</button>
                                        <button id="copy-html">Copy HTML</button>
                                        <button id="clear">Clear</button>
                                    </div>
                                    <script>
                                        const contentEl = document.getElementById('content');
                                        const statusEl = document.getElementById('status');
                                        let copyText = '';
                                        let copyHtml = '';

                                        window.chrome.webview.addEventListener('message', event => {
                                            console.log('WebView received host message:', event.data);
                                            try {
                                                const envelope = JSON.parse(event.data);
                                                console.log('WebView parsed host envelope:', envelope);
                                                handleHostEnvelope(envelope);
                                            } catch (err) {
                                                statusEl.textContent = 'Unable to parse host message';
                                                console.error('WebView host message parse error', err);
                                                reportUiFailure(null, 'invalid_json');
                                            }
                                        });

                                        function handleHostEnvelope(envelope) {
                                            if (!envelope || envelope.schema !== 'nvda.ui_host') {
                                                statusEl.textContent = 'Unknown host schema';
                                                reportUiFailure(envelope?.id ?? null, 'invalid_schema');
                                                return;
                                            }

                                            if (envelope.version !== 2) {
                                                statusEl.textContent = 'Unsupported host protocol version';
                                                reportUiFailure(envelope.id, 'unsupported_version');
                                                return;
                                            }

                                            if (envelope.type !== 'command' || !envelope.command?.name) {
                                                statusEl.textContent = 'Unknown host message type';
                                                reportUiFailure(envelope.id ?? null, 'unexpected_message_type');
                                                return;
                                            }

                                            const commandId = envelope.correlation_id || envelope.id;
                                            const payload = envelope.command.payload || {};
                                            statusEl.textContent = 'Command: ' + envelope.command.name;

                                            if (envelope.command.name === 'render_display') {
                                                copyText = payload.copy_text || payload.output_text || '';
                                                copyHtml = payload.copy_html || payload.output_html || '';
                                                if (payload.output_html) {
                                                    contentEl.innerHTML = payload.output_html;
                                                } else if (payload.output_text) {
                                                    contentEl.textContent = payload.output_text;
                                                } else {
                                                    contentEl.textContent = payload.message || 'No content available.';
                                                }
                                            } else if (envelope.command.name === 'open_chat') {
                                                copyText = payload.initial_text || '';
                                                copyHtml = '';
                                                const title = payload.title || 'Chat';
                                                contentEl.textContent = title + '\n\n' + (payload.initial_text || '');
                                            } else if (envelope.command.name === 'show_error') {
                                                contentEl.textContent = 'Error: ' + (payload.error_message || 'Unknown error');
                                                copyText = payload.error_message || '';
                                                copyHtml = '';
                                            } else if (envelope.command.name === 'update_progress') {
                                                contentEl.textContent = 'Progress: ' + (payload.message || '...');
                                                copyText = payload.message || '';
                                                copyHtml = '';
                                            } else if (envelope.command.name === 'close_window') {
                                                contentEl.textContent = 'Window closed by host command.';
                                                copyText = '';
                                                copyHtml = '';
                                            } else {
                                                contentEl.textContent = 'Unhandled command: ' + envelope.command.name;
                                                reportUiFailure(commandId, 'unknown_command');
                                                return;
                                            }

                                            reportUiApplied(commandId);
                                        }

                                        function reportUiApplied(commandId) {
                                            window.__sendHostEvent({
                                                schema: 'nvda.ui_host',
                                                version: 2,
                                                id: `web-ui-applied-${Date.now()}`,
                                                correlation_id: commandId,
                                                source: 'web_ui',
                                                type: 'event',
                                                event: {
                                                    name: 'ui_applied',
                                                    payload: { command_id: commandId },
                                                },
                                            });
                                        }

                                        function reportUiFailure(commandId, reason) {
                                            window.__sendHostEvent({
                                                schema: 'nvda.ui_host',
                                                version: 2,
                                                id: `web-ui-failed-${Date.now()}`,
                                                correlation_id: commandId,
                                                source: 'web_ui',
                                                type: 'event',
                                                event: {
                                                    name: 'ui_failed',
                                                    payload: { command_id: commandId, reason },
                                                },
                                            });
                                        }

                                        function copyToClipboard(text) {
                                            navigator.clipboard.writeText(text).then(() => {
                                                statusEl.textContent = 'Copied to clipboard.';
                                            }).catch(err => {
                                                statusEl.textContent = 'Copy failed.';
                                                console.error(err);
                                            });
                                        }

                                        document.getElementById('copy-text').onclick = () => copyToClipboard(copyText || contentEl.textContent || '');
                                        document.getElementById('copy-html').onclick = () => copyToClipboard(copyHtml || copyText || '');
                                        document.getElementById('clear').onclick = () => {
                                            contentEl.textContent = '';
                                            statusEl.textContent = 'Content cleared.';
                                        };
                                    </script>
                                </body>
                                </html>
                            "#),
                        ) {
                            eprintln!("NavigateToString failed: {:?}", e);
                        }

                        flush_pending_messages();
                        println!("Navigation started");

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
