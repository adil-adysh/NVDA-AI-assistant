use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};

use crate::app::ActivationPolicy;
use crate::logger;

#[derive(Debug, Clone)]
pub(crate) struct HostCommand {
    pub(crate) message: String,
    pub(crate) activation_policy: ActivationPolicy,
    pub(crate) request_webview_focus: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DeliveryOutcome {
    Delivered,
    DeferredVisibility,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum WebViewState {
    Uninitialized,
    EnvironmentReady,
    ControllerReady,
    NavigationStarted,
    WebUiReady,
    Ready,
}

static PENDING_MESSAGES: OnceLock<Mutex<Vec<HostCommand>>> = OnceLock::new();
static WEBVIEW_STATE: OnceLock<Mutex<WebViewState>> = OnceLock::new();
static WEBVIEW_READY: OnceLock<AtomicBool> = OnceLock::new();

fn pending_messages() -> &'static Mutex<Vec<HostCommand>> {
    PENDING_MESSAGES.get_or_init(|| Mutex::new(Vec::new()))
}

fn webview_state() -> &'static Mutex<WebViewState> {
    WEBVIEW_STATE.get_or_init(|| Mutex::new(WebViewState::Uninitialized))
}

fn webview_ready_flag() -> &'static AtomicBool {
    WEBVIEW_READY.get_or_init(|| AtomicBool::new(false))
}

pub(crate) fn pending_command_count() -> usize {
    pending_messages().lock().unwrap().len()
}

pub(crate) fn clear_pending_commands() {
    pending_messages().lock().unwrap().clear();
}

pub(crate) fn enqueue_pending_command(command: HostCommand) {
    pending_messages().lock().unwrap().push(command);
}

pub(crate) fn take_pending_commands() -> Vec<HostCommand> {
    let mut queue = pending_messages().lock().unwrap();
    std::mem::take(&mut *queue)
}

pub(crate) fn requeue_pending_commands(commands: Vec<HostCommand>) {
    if commands.is_empty() {
        return;
    }
    pending_messages().lock().unwrap().extend(commands);
}

pub(crate) fn current_webview_state() -> WebViewState {
    *webview_state().lock().unwrap()
}

pub(crate) fn set_webview_state(state: WebViewState) {
    let mut guard = webview_state().lock().unwrap();
    *guard = state;
    logger::info(&format!("WebView state changed to {:?}", state));
}

pub(crate) fn is_webview_ready() -> bool {
    webview_ready_flag().load(Ordering::SeqCst)
}

pub(crate) fn set_webview_ready(value: bool) {
    webview_ready_flag().store(value, Ordering::SeqCst);
}

pub(crate) fn host_ready() -> bool {
    current_webview_state() == WebViewState::Ready
}

pub(crate) fn flush_pending_commands<E>(
    mut deliver: impl FnMut(HostCommand) -> Result<DeliveryOutcome, E>,
    mut on_error: impl FnMut(&HostCommand, &E),
) {
    let count = pending_command_count();
    logger::info(&format!("FLUSH CALLED: queue_size={}", count));

    let queued_commands = take_pending_commands();
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
        match deliver(command.clone()) {
            Ok(DeliveryOutcome::Delivered) => {}
            Ok(DeliveryOutcome::DeferredVisibility) => deferred_commands.push(command),
            Err(error) => {
                on_error(&command, &error);
                deferred_commands.push(command);
            }
        }
    }
    if !deferred_commands.is_empty() {
        let deferred_count = deferred_commands.len();
        requeue_pending_commands(deferred_commands);
        logger::info(&format!(
            "Re-queued {} host message(s) pending a visible window",
            deferred_count
        ));
    }
    logger::debug("flush_pending_messages completed, queue drained");
}

pub(crate) fn window_ready_for_delivery(
    policy: ActivationPolicy,
    is_window_visible: impl Fn() -> bool,
    is_window_hidden: impl Fn() -> bool,
    should_activate_visible_window: impl Fn() -> bool,
    mut try_activate_window: impl FnMut(ActivationPolicy) -> bool,
) -> bool {
    let visible_before = is_window_visible();
    match policy {
        // NoActivate messages (streaming deltas, history sync, etc.) can be
        // delivered even when the parent window is hidden.  The WebView2
        // controller stays alive during a soft-dismiss (Escape key), so
        // JavaScript continues to receive and render streaming responses.
        // The host_ready() guard in post_host_command ensures the WebView
        // has been initialized — the HWND visibility is irrelevant.
        ActivationPolicy::NoActivate => visible_before || is_window_hidden(),
        ActivationPolicy::ActivateIfBackground => {
            if visible_before {
                if should_activate_visible_window() {
                    try_activate_window(policy)
                } else {
                    true
                }
            } else {
                try_activate_window(policy)
            }
        }
        ActivationPolicy::ActivateAndFocus => try_activate_window(policy),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[test]
    fn no_activate_allows_hidden_window_for_background_streaming() {
        // NoActivate (streaming, sync, etc.) should not be gated by HWND
        // visibility — the WebView2 controller stays alive and can receive
        // messages even while the parent window is dismissed via Escape.
        let ready = window_ready_for_delivery(
            ActivationPolicy::NoActivate,
            || false,
            || true,
            || panic!("should not inspect activation when no_activate"),
            |_| panic!("should not try to activate when no_activate"),
        );

        assert!(ready);
    }

    #[test]
    fn activate_if_background_activates_hidden_window() {
        let mut activated = false;
        let ready = window_ready_for_delivery(
            ActivationPolicy::ActivateIfBackground,
            || false,
            || true,
            || panic!("hidden window should not check foreground state"),
            |policy| {
                activated = true;
                policy == ActivationPolicy::ActivateIfBackground
            },
        );

        assert!(ready);
        assert!(activated);
    }

    #[test]
    fn activate_if_background_skips_activation_when_already_foreground() {
        let ready = window_ready_for_delivery(
            ActivationPolicy::ActivateIfBackground,
            || true,
            || false,
            || false,
            |_| panic!("foreground window should not activate again"),
        );

        assert!(ready);
    }

    #[test]
    fn activate_and_focus_uses_activation_result() {
        let ready = window_ready_for_delivery(
            ActivationPolicy::ActivateAndFocus,
            || false,
            || false,
            || panic!("activate_and_focus does not consult foreground state"),
            |_| false,
        );

        assert!(!ready);
    }

    #[test]
    fn flush_pending_commands_requeues_deferred_and_failed_commands() {
        clear_pending_commands();
        enqueue_pending_command(HostCommand {
            message: "delivered".to_string(),
            activation_policy: ActivationPolicy::NoActivate,
            request_webview_focus: false,
        });
        enqueue_pending_command(HostCommand {
            message: "deferred".to_string(),
            activation_policy: ActivationPolicy::ActivateIfBackground,
            request_webview_focus: false,
        });
        enqueue_pending_command(HostCommand {
            message: "failed".to_string(),
            activation_policy: ActivationPolicy::ActivateAndFocus,
            request_webview_focus: true,
        });

        let errors: RefCell<Vec<String>> = RefCell::new(Vec::new());
        flush_pending_commands(
            |command| match command.message.as_str() {
                "delivered" => Ok(DeliveryOutcome::Delivered),
                "deferred" => Ok(DeliveryOutcome::DeferredVisibility),
                _ => Err("send_failed"),
            },
            |command, error| {
                errors
                    .borrow_mut()
                    .push(format!("{}:{}", command.message, error));
            },
        );

        let pending = take_pending_commands();
        let pending_messages: Vec<String> = pending.into_iter().map(|command| command.message).collect();
        assert_eq!(pending_messages, vec!["deferred".to_string(), "failed".to_string()]);
        assert_eq!(errors.into_inner(), vec!["failed:send_failed".to_string()]);
    }
}
