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

pub(crate) fn window_ready_for_delivery(
    policy: ActivationPolicy,
    is_window_visible: impl Fn() -> bool,
    should_activate_visible_window: impl Fn() -> bool,
    mut try_activate_window: impl FnMut(ActivationPolicy) -> bool,
) -> bool {
    let visible_before = is_window_visible();
    match policy {
        ActivationPolicy::NoActivate => visible_before,
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

    #[test]
    fn no_activate_requires_visible_window() {
        let ready = window_ready_for_delivery(
            ActivationPolicy::NoActivate,
            || false,
            || panic!("should not inspect activation when no_activate"),
            |_| panic!("should not try to activate when no_activate"),
        );

        assert!(!ready);
    }

    #[test]
    fn activate_if_background_activates_hidden_window() {
        let mut activated = false;
        let ready = window_ready_for_delivery(
            ActivationPolicy::ActivateIfBackground,
            || false,
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
            |_| panic!("foreground window should not activate again"),
        );

        assert!(ready);
    }

    #[test]
    fn activate_and_focus_uses_activation_result() {
        let ready = window_ready_for_delivery(
            ActivationPolicy::ActivateAndFocus,
            || false,
            || panic!("activate_and_focus does not consult foreground state"),
            |_| false,
        );

        assert!(!ready);
    }
}
