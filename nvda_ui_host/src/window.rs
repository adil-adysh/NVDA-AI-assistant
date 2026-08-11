use std::ptr::null;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};
use windows::{
    core::{PCWSTR, Result, w},
    Win32::{
        Foundation::*,
        System::LibraryLoader::GetModuleHandleW,
        UI::WindowsAndMessaging::*,
    },
};

use serde_json::json;

use crate::ipc;
use crate::logger;
use crate::app::ActivationPolicy;
use crate::host_dispatch::HostCommand;

const WM_HOST_COMMAND: u32 = WM_APP + 1;
pub(crate) const WM_HOST_CLOSE: u32 = WM_APP + 2;
const WM_DEFERRED_FOCUS_WEBVIEW: u32 = WM_APP + 3;
const HOST_QUEUE_CAPACITY: usize = 128;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WindowState {
    Hidden,
    Visible,
    Closing,
}

static WINDOW_HANDLE: OnceLock<usize> = OnceLock::new();
static WINDOW_STATE: OnceLock<Mutex<WindowState>> = OnceLock::new();
static CLOSE_REASON: OnceLock<Mutex<Option<String>>> = OnceLock::new();
static HOST_COMMAND_QUEUE: OnceLock<Mutex<Vec<HostCommand>>> = OnceLock::new();
static PENDING_UI_APPLIED_FOCUS: OnceLock<AtomicBool> = OnceLock::new();

fn pending_ui_applied_focus() -> &'static AtomicBool {
    PENDING_UI_APPLIED_FOCUS.get_or_init(|| AtomicBool::new(false))
}

/// Called by the WebView event handler when `ui_applied` is received —
/// meaning Svelte has finished processing the command and `element.focus()`
/// has been called on the target element.  Only then is it safe to move
/// host-level focus into the WebView without NVDA reading the container
/// role ("pane").
pub(crate) fn request_deferred_focus_webview() {
    // Clear the gate flag so future WM_ACTIVATE events (e.g. Alt+Tab)
    // are allowed to call focus_webview directly.
    pending_ui_applied_focus().store(false, Ordering::SeqCst);
    if let Some(hwnd_value) = WINDOW_HANDLE.get() {
        let hwnd = HWND(*hwnd_value as _);
        unsafe {
            let _ = PostMessageW(Some(hwnd), WM_DEFERRED_FOCUS_WEBVIEW, WPARAM(0), LPARAM(0));
        }
    }
}

fn window_state() -> &'static Mutex<WindowState> {
    WINDOW_STATE.get_or_init(|| Mutex::new(WindowState::Hidden))
}

fn set_window_state(state: WindowState) {
    let mut guard = window_state().lock().unwrap();
    *guard = state;
}

fn current_window_state() -> WindowState {
    *window_state().lock().unwrap()
}

fn close_reason() -> &'static Mutex<Option<String>> {
    CLOSE_REASON.get_or_init(|| Mutex::new(None))
}

fn take_close_reason() -> Option<String> {
    let mut guard = close_reason().lock().unwrap();
    guard.take()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchError {
    QueueFull,
    QueueDisconnected,
    NotInitialized,
}

#[link(name = "user32")]
extern "system" {
    fn AttachThreadInput(id_attach: u32, id_attach_to: u32, attach: i32) -> i32;
    fn SetActiveWindow(hwnd: HWND) -> HWND;
}

#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentThreadId() -> u32;
}

pub fn create_window() -> Result<HWND> {
    unsafe {
        let h_instance = GetModuleHandleW(None)?;
        let class_name = w!("NVDA_UI_HOST");

        let wc = WNDCLASSW {
            lpfnWndProc: Some(wndproc),
            hInstance: h_instance.into(),
            lpszClassName: class_name,
            ..Default::default()
        };

        RegisterClassW(&wc);

        let hwnd = CreateWindowExW(
            Default::default(),
            class_name,
            w!("NVDA UI Host"),
            WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            900,
            700,
            None,
            None,
            Some(h_instance.into()),
            Some(null()),
        )?;

        Ok(hwnd)
    }
}

pub fn set_window_handle(hwnd: HWND) {
    let _ = WINDOW_HANDLE.set(hwnd.0 as usize);
}

fn to_wide_string(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}

pub fn set_window_title(title: &str) {
    if let Some(hwnd_value) = WINDOW_HANDLE.get() {
        let hwnd = HWND(*hwnd_value as _);
        let wide = to_wide_string(title);
        unsafe {
            let _ = SetWindowTextW(hwnd, PCWSTR(wide.as_ptr()));
        }
    }
}

pub fn initialize_host_dispatch(hwnd: HWND) {
    set_window_handle(hwnd);
    let _ = HOST_COMMAND_QUEUE.set(Mutex::new(Vec::new()));
    set_window_state(WindowState::Hidden);
    logger::info("Host dispatch queue initialized");
}

fn command_queue() -> &'static Mutex<Vec<HostCommand>> {
    HOST_COMMAND_QUEUE.get_or_init(|| Mutex::new(Vec::new()))
}

pub(crate) fn post_host_command(
    command: String,
    activation_policy: ActivationPolicy,
    request_webview_focus: bool,
) -> std::result::Result<(), DispatchError> {
    if let Some(hwnd_value) = WINDOW_HANDLE.get() {
        let mut queue = command_queue().lock().map_err(|_| DispatchError::QueueDisconnected)?;
        if queue.len() >= HOST_QUEUE_CAPACITY {
            logger::warn("Host dispatch queue full when posting command");
            return Err(DispatchError::QueueFull);
        }

        queue.push(HostCommand {
            message: command.clone(),
            activation_policy,
            request_webview_focus,
        });
        logger::info(&format!(
            "Queued host command, queue size={} activation_policy={:?} request_webview_focus={} command={}...",
            queue.len(),
            activation_policy,
            request_webview_focus,
            command.chars().take(80).collect::<String>()
        ));

        let hwnd = HWND(*hwnd_value as _);
        unsafe {
            let _ = PostMessageW(Some(hwnd), WM_HOST_COMMAND, WPARAM(0), LPARAM(0));
        }
        return Ok(());
    }

    Err(DispatchError::NotInitialized)
}

pub(crate) fn request_close_window(reason: &str) -> std::result::Result<(), DispatchError> {
    if let Some(hwnd_value) = WINDOW_HANDLE.get() {
        let state = current_window_state();
        if state != WindowState::Visible {
            logger::debug(&format!("request_close_window ignored because window state is {:?}", state));
            return Ok(());
        }

        let hwnd = HWND(*hwnd_value as _);
        logger::info(&format!("request_close_window(reason={}) accepted current_state={:?}", reason, state));
        let mut guard = close_reason().lock().map_err(|_| DispatchError::QueueDisconnected)?;
        *guard = Some(reason.to_string());
        unsafe {
            let _ = PostMessageW(Some(hwnd), WM_HOST_CLOSE, WPARAM(0), LPARAM(0));
        }
        return Ok(());
    }
    Err(DispatchError::NotInitialized)
}

/// Soft-dismiss the window: hide it without clearing command queues or
/// sending a close_host IPC event.  The WebView stays alive so streaming
/// responses continue to flow in the background.  When the next command
/// arrives with ActivateIfBackground (e.g. ChatStreamEnd) the window
/// will automatically re-appear with the full response visible.
pub(crate) fn dismiss_window() {
    if let Some(hwnd_value) = WINDOW_HANDLE.get() {
        let state = current_window_state();
        if state != WindowState::Visible {
            logger::debug(&format!("dismiss_window ignored because window state is {:?}", state));
            return;
        }
        let hwnd = HWND(*hwnd_value as _);
        logger::info("dismiss_window: hiding window (soft dismiss, queues preserved)");
        // Clear any pending focus gate so the next activation works correctly.
        pending_ui_applied_focus().store(false, Ordering::SeqCst);
        unsafe {
            if IsIconic(hwnd).as_bool() {
                let _ = ShowWindow(hwnd, SW_RESTORE);
            }
            let _ = ShowWindow(hwnd, SW_HIDE);
        }
        set_window_state(WindowState::Hidden);
        // Notify Python that the window was dismissed so it can set its
        // lifecycle to HIDDEN (preserving conversation for next open).
        let event_message = json!({
            "schema": "nvda.ui_host",
            "version": 2,
            "type": "event",
            "event": {
                "name": "close_host",
                "payload": {
                    "reason": "user_dismissed",
                    "source": "dismiss_window",
                }
            }
        })
        .to_string();
        ipc::queue_ui_event(event_message);
        logger::info("dismiss_window: complete, streaming will continue in background");
    }
}

fn drain_host_commands() {
    let messages = {
        let mut queue = command_queue().lock().unwrap();
        std::mem::take(&mut *queue)
    };

    if messages.is_empty() {
        logger::debug("drain_host_commands called with empty queue");
        return;
    }

    logger::info(&format!("Flushing {} queued host commands to WebView", messages.len()));
    for queued_command in messages {
        logger::debug(&format!(
            "Posting queued command to WebView activation_policy={:?} request_webview_focus={} command={}",
            queued_command.activation_policy,
            queued_command.request_webview_focus,
            queued_command.message.chars().take(120).collect::<String>()
        ));
        if let Err(error) = crate::webview::post_host_command(
            queued_command.message.as_str(),
            queued_command.activation_policy,
            queued_command.request_webview_focus,
        ) {
            logger::error(&format!("Failed to post command to WebView on UI thread: {:?}", error));
        }
    }
}

fn hwnd() -> HWND {
    HWND(*WINDOW_HANDLE.get().expect("window handle initialized") as _)
}

pub(crate) fn is_window_visible() -> bool {
    unsafe { IsWindowVisible(hwnd()).as_bool() }
}

pub(crate) fn is_window_hidden() -> bool {
    current_window_state() == WindowState::Hidden
}

pub(crate) fn should_activate_visible_window() -> bool {
    should_activate_window(hwnd())
}

pub(crate) fn try_activate_window(policy: ActivationPolicy) -> bool {
    let hwnd = hwnd();
    match policy {
        ActivationPolicy::NoActivate => {}
        ActivationPolicy::ActivateIfBackground => {
            if should_activate_window(hwnd) {
                activate_window(hwnd);
            }
        }
        ActivationPolicy::ActivateAndFocus => {
            activate_window(hwnd);
        }
    }

    is_window_visible()
}

fn clear_host_command_queue() {
    let mut queue = command_queue().lock().unwrap();
    if !queue.is_empty() {
        logger::info(&format!("Clearing {} queued host command(s) on window close", queue.len()));
        queue.clear();
    }
}

fn handle_window_close(hwnd: HWND, source: &str) -> LRESULT {
    let current_state = current_window_state();
    logger::info(&format!("Window close handler invoked from {} current_state={:?}", source, current_state));
    if current_state != WindowState::Visible {
        logger::debug("Window close ignored because window is not visible");
        return LRESULT(0);
    }

    set_window_state(WindowState::Closing);
    logger::info("Window state transitioning to Closing");
    clear_host_command_queue();
    crate::webview::clear_pending_messages();
    // Clear any pending focus gate so the next activation works correctly.
    pending_ui_applied_focus().store(false, Ordering::SeqCst);
    let reason = if source == "WM_CLOSE" {
        let _ = take_close_reason();
        "os_close".to_string()
    } else {
        take_close_reason().unwrap_or_else(|| "programmatic".to_string())
    };
    let event_message = json!({
        "schema": "nvda.ui_host",
        "version": 2,
        "type": "event",
        "event": {
            "name": "close_host",
            "payload": {
                "reason": reason,
                "source": source,
            }
        }
    })
    .to_string();
    ipc::queue_ui_event(event_message);
    let visible_before = unsafe { IsWindowVisible(hwnd).as_bool() };
    let iconic_before = unsafe { IsIconic(hwnd).as_bool() };
    logger::info(&format!("Window close before hide: hwnd={:?} visible_before={} iconic_before={} state={:?}", hwnd, visible_before, iconic_before, current_window_state()));
    unsafe {
        // Restore from minimized before hiding so the window cleanly
        // transitions out of the iconic state instead of staying hidden
        // while still logically minimized.
        if iconic_before {
            logger::info("Restoring minimized window before hiding");
            let _ = ShowWindow(hwnd, SW_RESTORE);
        }
        let _ = ShowWindow(hwnd, SW_HIDE);
    }
    let visible_after = unsafe { IsWindowVisible(hwnd).as_bool() };
    logger::info(&format!("ShowWindow(SW_HIDE) called; visible_after={} state=Hidden", visible_after));
    set_window_state(WindowState::Hidden);
    LRESULT(0)
}

fn activate_window(hwnd: HWND) {
    let visible_before = unsafe { IsWindowVisible(hwnd).as_bool() };
    let style_before = unsafe { GetWindowLongW(hwnd, GWL_STYLE) };
    logger::info(&format!("activate_window called hwnd={:?} visible_before={} style_before=0x{:x}", hwnd, visible_before, style_before));

    // Gate WM_ACTIVATE / WM_SETFOCUS from calling focus_webview()
    // synchronously.  SetForegroundWindow and ShowWindow fire these
    // messages, but the WebView hasn't received the open_chat /
    // render_display command yet, so no DOM element is focused.  NVDA
    // would read the container role ("pane") instead of the target
    // element.  We defer focus_webview until the WebView sends
    // ui_applied.  The gate must be armed BEFORE any window-activation
    // call (ShowWindow, SetForegroundWindow, etc.) so that inline
    // WM_SETFOCUS / WM_ACTIVATE messages from ShowWindow are also
    // captured.
    pending_ui_applied_focus().store(true, Ordering::SeqCst);

    unsafe {
        let result = if IsIconic(hwnd).as_bool() {
            ShowWindow(hwnd, SW_RESTORE)
        } else if visible_before {
            ShowWindow(hwnd, SW_SHOW)
        } else {
            ShowWindow(hwnd, SW_SHOWNORMAL)
        };
        // Always maximise the window when a user-initiated action brings
        // it forward so the full content and chat interface are visible.
        let _ = ShowWindow(hwnd, SW_MAXIMIZE);
        let _ = SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW,
        );
        let visible_mid = IsWindowVisible(hwnd).as_bool();
        let style_mid = GetWindowLongW(hwnd, GWL_STYLE);
        logger::info(&format!("activate_window show result={:?} visible_mid={} style_mid=0x{:x}", result, visible_mid, style_mid));

        let _ = SetWindowPos(
            hwnd,
            Some(HWND_TOPMOST),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE,
        );
        let _ = SetWindowPos(
            hwnd,
            Some(HWND_NOTOPMOST),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE,
        );
        let _ = BringWindowToTop(hwnd);

        let foreground = GetForegroundWindow();
        let current_thread_id = GetCurrentThreadId();
        let foreground_thread_id = if !foreground.0.is_null() {
            GetWindowThreadProcessId(foreground, None)
        } else {
            0
        };

        let attached = foreground_thread_id != 0
            && foreground_thread_id != current_thread_id
            && AttachThreadInput(foreground_thread_id, current_thread_id, 1) != 0;

        let foreground_result = SetForegroundWindow(hwnd);
        let _ = SetActiveWindow(hwnd);
        logger::debug(&format!("SetForegroundWindow result={:?}", foreground_result));

        if attached {
            let _ = AttachThreadInput(foreground_thread_id, current_thread_id, 0);
        }

        let visible_after = IsWindowVisible(hwnd).as_bool();
        let style_after = GetWindowLongW(hwnd, GWL_STYLE);
        if visible_after {
            set_window_state(WindowState::Visible);
            crate::webview::notify_window_visible();
        } else {
            logger::warn(&format!("activate_window did not make window visible hwnd={:?} visible_after={} style_after=0x{:x}", hwnd, visible_after, style_after));
        }
        logger::info(&format!("activate_window complete hwnd={:?} visible_after={} style_after=0x{:x}", hwnd, visible_after, style_after));
    }
}

fn should_activate_window(hwnd: HWND) -> bool {
    unsafe {
        if IsIconic(hwnd).as_bool() {
            return true;
        }
        GetForegroundWindow() != hwnd
    }
}

pub fn run_message_loop() {
    unsafe {
        let mut msg = MSG::default();

        while GetMessageW(&mut msg, None, 0, 0).into() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

unsafe extern "system" fn wndproc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_CLOSE => handle_window_close(hwnd, "WM_CLOSE"),
        WM_HOST_CLOSE => handle_window_close(hwnd, "WM_HOST_CLOSE"),
        WM_SETFOCUS => {
            // When the window is brought forward programmatically
            // (activate_window), focus is deferred until ui_applied.
            // The ui_applied handler posts WM_DEFERRED_FOCUS_WEBVIEW.
            // For user-initiated activation (Alt+Tab, click) the
            // pending flag won't be set, so we focus immediately.
            if !pending_ui_applied_focus().load(Ordering::SeqCst) {
                let _ = crate::webview::focus_webview();
            } else {
                logger::debug("WM_SETFOCUS: deferring focus_webview until ui_applied");
            }
            LRESULT(0)
        }
        WM_ACTIVATE => {
            if (wparam.0 & 0xFFFF) != WA_INACTIVE as usize {
                if !pending_ui_applied_focus().load(Ordering::SeqCst) {
                    let _ = crate::webview::focus_webview();
                } else {
                    logger::debug("WM_ACTIVATE: deferring focus_webview until ui_applied");
                }
            }
            DefWindowProcW(hwnd, msg, wparam, lparam)
        }
        WM_DEFERRED_FOCUS_WEBVIEW => {
            logger::debug("WM_DEFERRED_FOCUS_WEBVIEW: applying deferred focus_webview");
            let _ = crate::webview::focus_webview();
            LRESULT(0)
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            LRESULT(0)
        }
        WM_SIZE => {
            let minimized = wparam.0 as u32 == SIZE_MINIMIZED;
            let restored = wparam.0 as u32 == SIZE_RESTORED;
            if minimized {
                logger::info("Window minimized by user; tracking state");
            } else if restored {
                logger::info("Window restored from minimized; ensuring WebView focus");
                let _ = crate::webview::focus_webview();
            }
            crate::webview::resize_webview(hwnd);
            LRESULT(0)
        }
        WM_KEYDOWN => {
            // Native Escape fallback: when WebView loses focus, the JS keyboard
            // handler won't fire.  Handle Escape here so the window can always
            // be dismissed even in edge cases (minimized, focus stolen, etc.).
            if wparam.0 == 0x1B /* VK_ESCAPE */ {
                logger::info("Escape key received by native window procedure; dismissing window");
                dismiss_window();
                return LRESULT(0);
            }
            DefWindowProcW(hwnd, msg, wparam, lparam)
        }
        WM_HOST_COMMAND => {
            logger::debug("Window procedure received WM_HOST_COMMAND");
            let _ = wparam;
            let _ = lparam;
            drain_host_commands();
            LRESULT(0)
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}
