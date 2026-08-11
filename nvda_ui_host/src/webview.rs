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
use serde_json::Value;
use webview2_com::Microsoft::Web::WebView2::Win32::*;
use webview2_com::{
    AddScriptToExecuteOnDocumentCreatedCompletedHandler,
    CreateCoreWebView2ControllerCompletedHandler, CreateCoreWebView2EnvironmentCompletedHandler,
    NavigationCompletedEventHandler, WebMessageReceivedEventHandler,
};

use crate::ipc;

// ── Included sub-modules ──────────────────────────────────────────────
// These share the parent module's imports and namespace.
include!("webview_state.rs");
include!("webview_delivery.rs");
include!("webview_events.rs");
// ──────────────────────────────────────────────────────────────────────

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
                                    // Listen for incoming host commands sent via PostWebMessageAsString.
                                    // The bridge also registers its own listener, but this one runs early
                                    // (before page scripts) so no message is ever dropped.
                                    window.chrome.webview.addEventListener('message', function(event) {
                                        if (typeof event.data === 'string' && event.data.length > 0) {
                                            if (window.__receiveHostCommand) {
                                                window.__receiveHostCommand(event.data);
                                            }
                                        }
                                    });
                                    (function() {
                                        var _orig = {
                                            log: console.log.bind(console),
                                            warn: console.warn.bind(console),
                                            error: console.error.bind(console)
                                        };
                                        function forward(level, args) {
                                            try {
                                                var msg = Array.from(args).map(function(a) {
                                                    if (a instanceof Error) return a.message + (a.stack ? '\n' + a.stack : '');
                                                    if (typeof a === 'object') {
                                                        try { return JSON.stringify(a); } catch(_) { return String(a); }
                                                    }
                                                    return String(a);
                                                }).join(' ');
                                                window.chrome.webview.postMessage(JSON.stringify({
                                                    type: 'log',
                                                    level: level,
                                                    message: msg
                                                }));
                                            } catch(_) {}
                                            _orig[level].apply(console, args);
                                        }
                                        console.log = function() { forward('log', arguments); };
                                        console.warn = function() { forward('warn', arguments); };
                                        console.error = function() { forward('error', arguments); };
                                    })();
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
                                // Safety net: if the web_ui_ready event arrived before
                                // this callback fired (or was missed), try to transition
                                // to Ready so queued commands are flushed.
                                maybe_transition_to_ready();
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
