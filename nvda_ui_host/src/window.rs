use std::ptr::null;
use std::sync::{Mutex, OnceLock};
use windows::{
    core::{PCWSTR, Result, w},
    Win32::{
        Foundation::*,
        System::LibraryLoader::GetModuleHandleW,
        UI::WindowsAndMessaging::*,
    },
};

use crate::logger;

const WM_HOST_COMMAND: u32 = WM_APP + 1;
const HOST_QUEUE_CAPACITY: usize = 128;

static WINDOW_HANDLE: OnceLock<usize> = OnceLock::new();
static HOST_COMMAND_QUEUE: OnceLock<Mutex<Vec<String>>> = OnceLock::new();

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchError {
    QueueFull,
    QueueDisconnected,
    NotInitialized,
}

#[link(name = "user32")]
extern "system" {
    fn SetFocus(hwnd: HWND) -> HWND;
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
    logger::info("Host dispatch queue initialized");
}

fn command_queue() -> &'static Mutex<Vec<String>> {
    HOST_COMMAND_QUEUE.get_or_init(|| Mutex::new(Vec::new()))
}

pub fn post_host_command(command: String) -> std::result::Result<(), DispatchError> {
    if let Some(hwnd_value) = WINDOW_HANDLE.get() {
        let mut queue = command_queue().lock().map_err(|_| DispatchError::QueueDisconnected)?;
        if queue.len() >= HOST_QUEUE_CAPACITY {
            logger::warn("Host dispatch queue full when posting command");
            return Err(DispatchError::QueueFull);
        }

        queue.push(command.clone());
        logger::info(&format!("Queued host command, queue size={} command={}...", queue.len(), command.chars().take(80).collect::<String>()));

        let hwnd = HWND(*hwnd_value as _);
        unsafe {
            let _ = PostMessageW(Some(hwnd), WM_HOST_COMMAND, WPARAM(0), LPARAM(0));
        }
        return Ok(());
    }

    Err(DispatchError::NotInitialized)
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
    show_and_focus_window();
    for command in messages {
        logger::debug(&format!("Posting queued command to WebView: {}", command.chars().take(120).collect::<String>()));
        if let Err(error) = crate::webview::post_host_command(command.as_str()) {
            logger::error(&format!("Failed to post command to WebView on UI thread: {:?}", error));
        }
    }
}

fn activate_window(hwnd: HWND) {
    unsafe {
        if IsIconic(hwnd).as_bool() {
            let _ = ShowWindow(hwnd, SW_RESTORE);
        } else {
            let _ = ShowWindow(hwnd, SW_SHOW);
        }

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

        let _ = SetForegroundWindow(hwnd);
        let _ = SetActiveWindow(hwnd);
        let _ = SetFocus(hwnd);

        if attached {
            let _ = AttachThreadInput(foreground_thread_id, current_thread_id, 0);
        }
    }
}

pub fn show_and_focus_window() {
    if let Some(hwnd_value) = WINDOW_HANDLE.get() {
        let hwnd = HWND(*hwnd_value as _);
        activate_window(hwnd);
        let _ = crate::webview::focus_webview();
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
        WM_CLOSE => {
            let _ = ShowWindow(hwnd, SW_HIDE);
            LRESULT(0)
        }
        WM_SETFOCUS => {
            let _ = crate::webview::focus_webview();
            LRESULT(0)
        }
        WM_ACTIVATE => {
            if (wparam.0 & 0xFFFF) != WA_INACTIVE as usize {
                let _ = crate::webview::focus_webview();
            }
            DefWindowProcW(hwnd, msg, wparam, lparam)
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            LRESULT(0)
        }
        WM_SIZE => {
            crate::webview::resize_webview(hwnd);
            LRESULT(0)
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
