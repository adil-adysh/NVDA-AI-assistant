use std::ptr::null;
use std::sync::{mpsc, Mutex, OnceLock};
use windows::{
    core::{Result, w},
    Win32::{
        Foundation::*,
        System::LibraryLoader::GetModuleHandleW,
        UI::WindowsAndMessaging::*,
    },
};

const WM_HOST_COMMAND: u32 = WM_APP + 1;
const HOST_QUEUE_CAPACITY: usize = 128;

static WINDOW_HANDLE: OnceLock<usize> = OnceLock::new();
static HOST_COMMAND_SENDER: OnceLock<mpsc::SyncSender<String>> = OnceLock::new();
static HOST_COMMAND_RECEIVER: OnceLock<Mutex<mpsc::Receiver<String>>> = OnceLock::new();

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchError {
    QueueFull,
    QueueDisconnected,
    NotInitialized,
}

#[link(name = "user32")]
extern "system" {
    fn SetFocus(hwnd: HWND) -> HWND;
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
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            900,
            700,
            None,
            None,
            Some(h_instance.into()),
            Some(null()),
        )?;

        let _ = ShowWindow(hwnd, SW_SHOW);

        Ok(hwnd)
    }
}

pub fn set_window_handle(hwnd: HWND) {
    let _ = WINDOW_HANDLE.set(hwnd.0 as usize);
}

pub fn initialize_host_dispatch(hwnd: HWND) {
    set_window_handle(hwnd);
    let (sender, receiver) = mpsc::sync_channel(HOST_QUEUE_CAPACITY);
    let _ = HOST_COMMAND_SENDER.set(sender);
    let _ = HOST_COMMAND_RECEIVER.set(Mutex::new(receiver));
}

pub fn post_host_command(command: String) -> std::result::Result<(), DispatchError> {
    let Some(sender) = HOST_COMMAND_SENDER.get() else {
        return Err(DispatchError::NotInitialized);
    };
    if let Some(hwnd_value) = WINDOW_HANDLE.get() {
        match sender.try_send(command) {
            Ok(()) => {}
            Err(mpsc::TrySendError::Full(_)) => return Err(DispatchError::QueueFull),
            Err(mpsc::TrySendError::Disconnected(_)) => return Err(DispatchError::QueueDisconnected),
        }
        let hwnd = HWND(*hwnd_value as _);
        unsafe {
            let _ = PostMessageW(Some(hwnd), WM_HOST_COMMAND, WPARAM(0), LPARAM(0));
        }
        return Ok(());
    }

    Err(DispatchError::NotInitialized)
}

fn drain_host_commands() {
    let Some(receiver_mutex) = HOST_COMMAND_RECEIVER.get() else {
        return;
    };

    let receiver = receiver_mutex.lock().unwrap();
    loop {
        match receiver.try_recv() {
            Ok(command) => {
                if let Err(error) = crate::webview::post_host_command(command.as_str()) {
                    eprintln!("Failed to post command to WebView on UI thread: {:?}", error);
                }
            }
            Err(mpsc::TryRecvError::Empty) | Err(mpsc::TryRecvError::Disconnected) => break,
        }
    }
}

pub unsafe fn focus_window(hwnd: HWND) -> HWND {
    let _ = SetForegroundWindow(hwnd);
    SetFocus(hwnd)
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
        WM_DESTROY => {
            PostQuitMessage(0);
            LRESULT(0)
        }
        WM_SIZE => {
            crate::webview::resize_webview(hwnd);
            LRESULT(0)
        }
        WM_HOST_COMMAND => {
            let _ = wparam;
            let _ = lparam;
            drain_host_commands();
            LRESULT(0)
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}
